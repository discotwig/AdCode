"""Email bot webhook server.

Receives inbound emails forwarded by the Cloudflare Email Worker, dispatches
them through the plan-review pipeline, and sends outbound replies via Resend.

Start:
    uvicorn src.email_bot:app --host 0.0.0.0 --port 8080
"""
import email as email_lib
import json
import logging
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import anthropic
from dotenv import dotenv_values, load_dotenv
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException

from src.api.meta import MetaClient
from src.services.email import send_email, EmailMessage
from src.services.ingest import read_excel, extract_campaigns
from src.prompts import AMBIGUITY_EMAIL
from src.services.brief import extract_from_text
from src.services.state import StateFile
from src.services.validate import validate_all
from src.traffic import plan, apply as apply_plan

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CUSTOMERS_DIR = _REPO_ROOT / "customers"
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

PENDING_EXPIRY_HOURS = 24


@asynccontextmanager
async def _lifespan(app: FastAPI):
    try:
        _scan_expired_pending()
    except Exception:
        logger.exception("Expired pending scan failed on startup")
    yield


app = FastAPI(lifespan=_lifespan)


# ------------------------------------------------------------------
# Startup — expired pending brief sweep
# ------------------------------------------------------------------


def _scan_expired_pending():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=PENDING_EXPIRY_HOURS)
    configs = _load_all_configs()
    for customer in configs:
        config_dir: Path = customer["_config_dir"]
        env: dict = customer["_env"]
        state_dir = config_dir / customer.get("state_dir", "state")
        bot_email = customer.get("bot_email", "traffic@ryanbishop.me")
        operator_email = customer.get("operator_email", "")
        resend_key = env.get("RESEND_API_KEY") or os.environ.get("RESEND_API_KEY", "")

        for pending_path in sorted(state_dir.glob(".pending_*.json")):
            try:
                pending = json.loads(pending_path.read_text(encoding="utf-8"))
                created_at = datetime.fromisoformat(pending["created_at"])
                if created_at >= cutoff:
                    continue
                # Expired — notify operator and clean up
                client_from = pending.get("client_from", "unknown")
                client_subject = pending.get("client_subject", "(no subject)")
                created_str = created_at.strftime("%Y-%m-%d %H:%M UTC")
                body = (
                    f"A pending brief expired without a GO/HOLD response and was discarded.\n\n"
                    f"From: {client_from}\n"
                    f"Subject: {client_subject}\n"
                    f"Received: {created_str}\n\n"
                    f"If this brief should be actioned, ask the client to resend."
                )
                if operator_email and resend_key:
                    send_email(EmailMessage(
                        from_=bot_email,
                        to=operator_email,
                        subject=f"[AdCode] Expired brief: {client_subject}",
                        html=body.replace("\n", "<br>"),
                    ), resend_key)
                pending_path.unlink()
                logger.info("Expired pending_id=%s from=%s", pending.get("pending_id"), client_from)
            except Exception:
                logger.exception("Failed to process expired pending file %s", pending_path)


# ------------------------------------------------------------------
# Config loading
# ------------------------------------------------------------------

def _load_all_configs() -> list[dict]:
    configs = []
    for config_path in CUSTOMERS_DIR.glob("*/config.json"):
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["_config_dir"] = config_path.parent
        env_path = config_path.parent / ".env"
        cfg["_env"] = dotenv_values(env_path) if env_path.exists() else {}
        configs.append(cfg)
    return configs


def _bare_email(addr: str) -> str:
    """Extract bare email from 'Display Name <email@example.com>'."""
    if "<" in addr:
        addr = addr.split("<")[-1].rstrip(">")
    return addr.strip().lower()


def _find_customer(from_addr: str, configs: list[dict]) -> dict | None:
    bare = _bare_email(from_addr)
    for cfg in configs:
        approved = [a.lower() for a in cfg.get("email_addresses", [])]
        if bare in approved:
            return cfg
        if bare == cfg.get("operator_email", "").lower():
            return cfg
    return None


# ------------------------------------------------------------------
# Email parsing
# ------------------------------------------------------------------

def _parse_raw_email(raw: str) -> dict:
    msg = email_lib.message_from_string(raw)
    result: dict = {
        "subject": msg.get("Subject", ""),
        "from": msg.get("From", ""),
        "message_id": msg.get("Message-ID", "").strip(),
        "in_reply_to": msg.get("In-Reply-To", "").strip(),
        "body": "",
        "xlsx_bytes": None,
        "xlsx_filename": None,
    }
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            fn = part.get_filename()
            if ct == "text/plain" and not result["body"]:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    result["body"] = payload.decode(charset, errors="replace")
            elif fn and fn.lower().endswith(".xlsx") and result["xlsx_bytes"] is None:
                result["xlsx_bytes"] = part.get_payload(decode=True)
                result["xlsx_filename"] = fn
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            result["body"] = payload.decode(charset, errors="replace")
    return result


# ------------------------------------------------------------------
# Plan formatting
# ------------------------------------------------------------------

def _format_plan_text(p) -> str:
    lines = [p.summary(), ""]
    for op in p.operations:
        op_type = type(op).__name__
        cname = getattr(op, "campaign_name", None) or getattr(op, "campaign", {}).get("name", "")
        aname = getattr(op, "adset_name", "")
        fb_id = getattr(op, "fb_id", "")
        if op_type.startswith("Delete"):
            label = op_type.replace("Delete", "").lower()
            detail = " / ".join(filter(None, [cname, aname]))
            lines.append(f"  DELETE {label}: \"{detail}\"  (fb_id: {fb_id})")
        elif hasattr(op, "changed_fields"):
            suffix = f" / {aname}" if aname else ""
            lines.append(f"  {op_type}: {cname}{suffix} — {list(op.changed_fields.keys())}")
        else:
            suffix = f" / {aname}" if aname else ""
            lines.append(f"  {op_type}: {cname}{suffix}")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Inbound handler — new brief from client
# ------------------------------------------------------------------

async def _handle_inbound(parsed: dict, customer: dict):
    subject = parsed["subject"]
    from_addr = parsed["from"]
    config_dir: Path = customer["_config_dir"]
    env: dict = customer["_env"]
    account_id: str = customer["account_id"]
    state_dir = config_dir / customer.get("state_dir", "state")
    bot_email = customer.get("bot_email", "traffic@ryanbishop.me")
    operator_email = customer.get("operator_email", "")
    resend_key = env.get("RESEND_API_KEY") or os.environ.get("RESEND_API_KEY", "")

    ai_client = anthropic.Anthropic(
        api_key=env.get("ANTHROPIC_API_KEY") or os.environ["ANTHROPIC_API_KEY"],
        max_retries=4,
    )

    def _reply_client(body_text: str):
        send_email(EmailMessage(
            from_=bot_email,
            to=_bare_email(from_addr),
            subject=f"Re: {subject}",
            html=body_text.replace("\n", "<br>"),
            reply_to=bot_email,
            in_reply_to=parsed["message_id"] or None,
        ), resend_key)

    # --- Extract campaigns ---
    if parsed["xlsx_bytes"]:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(parsed["xlsx_bytes"])
            tmp_path = tmp.name
        try:
            excel_data = read_excel(tmp_path)
            ingest_result = extract_campaigns(excel_data, ai_client)
        finally:
            os.unlink(tmp_path)
    else:
        ingest_result = extract_from_text(parsed["body"], ai_client)

    if not ingest_result.campaigns:
        _reply_client(
            "We couldn't extract any campaign definitions from your brief. "
            "Please send an Excel file or a more detailed plain-text description."
        )
        return

    if ingest_result.ambiguities:
        ambiguity_list = "\n".join(
            f"- {a.question}" for a in ingest_result.ambiguities
        )
        consultant_prompt = AMBIGUITY_EMAIL.format(
            subject=subject,
            campaigns_json=json.dumps(ingest_result.campaigns, indent=2),
            ambiguity_list=ambiguity_list,
        )
        amb_response = ai_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": consultant_prompt}],
        )
        _reply_client(amb_response.content[0].text.strip())
        return

    campaign_json = {"account_id": account_id, "campaigns": ingest_result.campaigns}

    # --- Validate ---
    meta = MetaClient(
        app_id=env.get("FB_APP_ID") or os.environ["FB_APP_ID"],
        app_secret=env.get("FB_APP_SECRET") or os.environ["FB_APP_SECRET"],
        access_token=env.get("FB_ACCESS_TOKEN") or os.environ["FB_ACCESS_TOKEN"],
        account_id=account_id,
    )
    validation = validate_all(campaign_json, ai_client)
    if not validation.is_pushable:
        _reply_client(
            "Your brief could not be processed due to policy or schema issues:\n\n"
            + validation.summary()
        )
        return

    # --- Plan ---
    state = StateFile.load(account_id, state_dir=state_dir)
    p = plan(campaign_json, state, meta)

    # --- Save pending file ---
    pending_id = uuid.uuid4().hex[:8]
    pending_path = state_dir / f".pending_{pending_id}.json"
    state_dir.mkdir(parents=True, exist_ok=True)
    pending_path.write_text(json.dumps({
        "pending_id": pending_id,
        "message_id": parsed["message_id"],
        "client_from": from_addr,
        "client_subject": subject,
        "campaign_json": campaign_json,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2), encoding="utf-8")

    # --- Email operator ---
    plan_text = _format_plan_text(p)
    op_subject = f"[AdCode Review] {pending_id} | {subject}"
    op_body = (
        f"New campaign brief from: {from_addr}\n\n"
        f"--- Plan ---\n{plan_text}\n\n"
        f"Reply GO to apply or HOLD to discard."
    )
    send_email(EmailMessage(
        from_=bot_email,
        to=operator_email,
        subject=op_subject,
        html=op_body.replace("\n", "<br>"),
    ), resend_key)
    logger.info("Sent plan to operator for pending_id=%s", pending_id)


# ------------------------------------------------------------------
# Operator reply handler — GO / HOLD
# ------------------------------------------------------------------

async def _handle_operator_reply(parsed: dict, customer: dict):
    subject = parsed["subject"]
    body_upper = parsed["body"].strip().upper()
    config_dir: Path = customer["_config_dir"]
    env: dict = customer["_env"]
    account_id: str = customer["account_id"]
    state_dir = config_dir / customer.get("state_dir", "state")
    bot_email = customer.get("bot_email", "traffic@ryanbishop.me")
    resend_key = env.get("RESEND_API_KEY") or os.environ.get("RESEND_API_KEY", "")

    # Extract pending_id from subject: "[AdCode Review] {pending_id} | ..."
    try:
        pending_id = subject.split("[AdCode Review]")[1].split("|")[0].strip()
    except (IndexError, ValueError):
        logger.warning("Operator reply missing pending_id in subject: %r", subject)
        return

    pending_path = state_dir / f".pending_{pending_id}.json"
    if not pending_path.exists():
        logger.warning("No pending file for id=%s", pending_id)
        return

    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    client_from = pending["client_from"]
    client_subject = pending["client_subject"]
    campaign_json = pending["campaign_json"]

    def _reply_client(body_text: str):
        send_email(EmailMessage(
            from_=bot_email,
            to=_bare_email(client_from),
            subject=f"Re: {client_subject}",
            html=body_text.replace("\n", "<br>"),
            in_reply_to=pending.get("message_id") or None,
        ), resend_key)

    is_go = "GO" in body_upper
    is_hold = "HOLD" in body_upper

    if not is_go and not is_hold:
        logger.warning("Operator reply contained neither GO nor HOLD: %r", parsed["body"][:100])
        return

    if is_hold:
        _reply_client(
            "Your campaign brief is currently on hold. "
            "We'll be in touch if we have questions."
        )
        pending_path.unlink()
        logger.info("HOLD — discarded pending_id=%s", pending_id)
        return

    # GO — apply
    meta = MetaClient(
        app_id=env.get("FB_APP_ID") or os.environ["FB_APP_ID"],
        app_secret=env.get("FB_APP_SECRET") or os.environ["FB_APP_SECRET"],
        access_token=env.get("FB_ACCESS_TOKEN") or os.environ["FB_ACCESS_TOKEN"],
        account_id=account_id,
    )
    ai_client = anthropic.Anthropic(
        api_key=env.get("ANTHROPIC_API_KEY") or os.environ["ANTHROPIC_API_KEY"],
        max_retries=4,
    )

    state = StateFile.load(account_id, state_dir=state_dir)
    p = plan(campaign_json, state, meta)
    result = apply_plan(p, meta, state, campaign_json=campaign_json)

    _reply_client(
        f"Your campaigns have been applied to Facebook.\n\nSummary: {result.summary()}"
    )
    pending_path.unlink()
    logger.info("GO — applied pending_id=%s result=%s", pending_id, result.summary())


# ------------------------------------------------------------------
# Webhook endpoint
# ------------------------------------------------------------------

@app.post("/inbound")
async def inbound_webhook(request: Request):
    if WEBHOOK_SECRET:
        if request.headers.get("X-Webhook-Secret", "") != WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid webhook secret")

    data = await request.json()
    from_addr: str = data.get("from", "")
    raw: str = data.get("raw", "")

    configs = _load_all_configs()
    customer = _find_customer(from_addr, configs)

    if customer is None:
        logger.warning("Rejected email from unknown sender: %s", from_addr)
        return {"status": "rejected", "reason": "unknown sender"}

    parsed = _parse_raw_email(raw)
    bare_from = _bare_email(from_addr)
    operator_email = customer.get("operator_email", "").lower()

    # Ensure parsed["from"] is never empty — fall back to the webhook envelope address
    if not parsed["from"]:
        parsed["from"] = from_addr

    if bare_from == operator_email and "[AdCode Review]" in parsed["subject"]:
        await _handle_operator_reply(parsed, customer)
    else:
        await _handle_inbound(parsed, customer)

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}
