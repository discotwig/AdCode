"""Email bot webhook server — mailroom mode.

Receives inbound emails forwarded by the Cloudflare Email Worker.
Validates submissions and routes them:

  Path 1 — Valid AdCode template (.json passes schema):
    → Reply client: "Request received and submitted"
    → Forward template to operator as email attachment

  Path 2 — JSON attachment fails schema:
    → Reply client with specific validation errors and fix instructions

  Path 3 — Dirty Excel or plain-text brief:
    → Seed a starter template via AI ingestion
    → Reply client with seeded .json attached and review instructions

The bot holds no Facebook credentials and no state files.
Engine (plan/apply) runs on the operator's local machine.

Start:
    uvicorn src.email_bot:app --host 0.0.0.0 --port 8080
"""
import email as email_lib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import anthropic
import jsonschema
from anthropic import APIStatusError
from dotenv import dotenv_values, load_dotenv
from fastapi import FastAPI, Request, HTTPException

import markdown as markdown_lib

from src.services.email import send_email, EmailMessage
from src.services.ingest import read_excel, extract_campaigns
from src.services.brief import extract_from_text
from src.traffic import _CAMPAIGN_SCHEMA

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CUSTOMERS_DIR = _REPO_ROOT / "customers"
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

app = FastAPI()


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
        "json_bytes": None,
        "json_filename": None,
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
            elif fn and fn.lower().endswith(".json") and result["json_bytes"] is None:
                result["json_bytes"] = part.get_payload(decode=True)
                result["json_filename"] = fn
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            result["body"] = payload.decode(charset, errors="replace")
    return result


def _to_html(text: str) -> str:
    """Convert markdown or plain text to HTML for email sending."""
    return markdown_lib.markdown(text, extensions=["nl2br", "tables"])


def _format_schema_errors(errors: list) -> str:
    """Format jsonschema ValidationErrors into a readable list for the client."""
    lines = ["The following issues were found in your template:\n"]
    for i, err in enumerate(errors, 1):
        path = " → ".join(str(p) for p in err.absolute_path) if err.absolute_path else "root"
        lines.append(f"{i}. **{path}**: {err.message}")
    lines.append(
        "\nPlease fix these issues and resubmit your template. "
        "If you need help, reply to this email with your questions."
    )
    return "\n".join(lines)


# ------------------------------------------------------------------
# Inbound handler — three-path routing
# ------------------------------------------------------------------

async def _handle_inbound(parsed: dict, customer: dict):
    from_addr = parsed["from"]
    subject = parsed["subject"]
    env: dict = customer["_env"]
    account_id: str = customer["account_id"]
    bot_email = customer.get("bot_email", "traffic@ryanbishop.me")
    operator_email = customer.get("operator_email", "")
    resend_key = env.get("RESEND_API_KEY") or os.environ.get("RESEND_API_KEY", "")

    def _reply_client(
        body_text: str,
        attachment_bytes: bytes | None = None,
        attachment_filename: str | None = None,
    ):
        send_email(EmailMessage(
            from_=bot_email,
            to=_bare_email(from_addr),
            subject=f"Re: {subject}",
            html=_to_html(body_text),
            reply_to=bot_email,
            in_reply_to=parsed["message_id"] or None,
            attachment_bytes=attachment_bytes,
            attachment_filename=attachment_filename,
        ), resend_key)

    # ------------------------------------------------------------------
    # Path 1 / 2 — JSON attachment present
    # ------------------------------------------------------------------
    if parsed["json_bytes"]:
        try:
            campaign_json = json.loads(parsed["json_bytes"].decode("utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            _reply_client(
                f"Your template could not be read as JSON: {exc}\n\n"
                "Please ensure the file is saved as a valid `.json` file and resubmit."
            )
            return

        validator = jsonschema.Draft7Validator(_CAMPAIGN_SCHEMA)
        errors = sorted(
            validator.iter_errors(campaign_json),
            key=lambda e: list(e.absolute_path),
        )

        if not errors:
            # Path 1 — valid template: ack client, forward to operator
            _reply_client(
                "Your request has been received and submitted for processing. "
                "You'll hear from us once your campaigns are live."
            )
            if operator_email:
                send_email(EmailMessage(
                    from_=bot_email,
                    to=operator_email,
                    subject=f"[AdCode] Template submission | {subject}",
                    html=_to_html(
                        f"**New template submission**\n\n"
                        f"From: {from_addr}\n"
                        f"Subject: {subject}\n"
                        f"Account: `{account_id}`\n\n"
                        f"The validated template is attached. "
                        f"Save it to `customers/<slug>/campaigns/` and run:\n\n"
                        f"```\npython src/mcp_server.py --config customers/<slug>/config.json\n```"
                    ),
                    attachment_bytes=parsed["json_bytes"],
                    attachment_filename=parsed["json_filename"] or "campaign.json",
                ), resend_key)
            logger.info("Valid template forwarded to operator from=%s account=%s", from_addr, account_id)

        else:
            # Path 2 — schema errors: return errors to client, do not forward
            _reply_client(_format_schema_errors(errors))
            logger.info(
                "Schema errors returned to client from=%s errors=%d",
                from_addr, len(errors),
            )
        return

    # ------------------------------------------------------------------
    # Path 3 — xlsx or plain text: seed a starter template
    # ------------------------------------------------------------------
    ai_client = anthropic.Anthropic(
        api_key=env.get("ANTHROPIC_API_KEY") or os.environ["ANTHROPIC_API_KEY"],
        max_retries=6,
    )

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
            "We couldn't extract any campaign definitions from your submission.\n\n"
            "To submit a campaign request, please attach a valid AdCode template (`.json`) "
            "or an Excel file with your campaign details."
        )
        return

    seeded = {"account_id": account_id, "campaigns": ingest_result.campaigns}
    seeded_bytes = json.dumps(seeded, indent=2).encode("utf-8")

    body = (
        "We've created a starter template from your submission — it's attached to this email.\n\n"
        "**Next steps:**\n"
        "1. Open the attached `campaign_template.json` file and review every field\n"
        "2. Fill in any fields that are missing or marked incomplete\n"
        "3. Reply to this email with the completed template attached\n\n"
        "Once we receive your completed template, we'll apply your campaigns and confirm."
    )

    if ingest_result.ambiguities:
        amb_lines = "\n".join(f"- {a.question}" for a in ingest_result.ambiguities)
        body += f"\n\n**Fields that need your attention:**\n{amb_lines}"

    _reply_client(body, attachment_bytes=seeded_bytes, attachment_filename="campaign_template.json")
    logger.info(
        "Seeded template returned to client from=%s campaigns=%d ambiguities=%d",
        from_addr, len(ingest_result.campaigns), len(ingest_result.ambiguities),
    )


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

    # Ensure parsed["from"] is never empty — fall back to the webhook envelope address
    if not parsed["from"]:
        parsed["from"] = from_addr

    try:
        await _handle_inbound(parsed, customer)
    except APIStatusError as exc:
        if exc.status_code == 529:
            logger.warning("Anthropic overloaded — returning 200 to avoid Worker rejection")
            bot_email = customer.get("bot_email", "traffic@ryanbishop.me")
            resend_key = customer["_env"].get("RESEND_API_KEY") or os.environ.get("RESEND_API_KEY", "")
            if resend_key and parsed.get("from"):
                try:
                    send_email(EmailMessage(
                        from_=bot_email,
                        to=_bare_email(parsed["from"]),
                        subject=f"Re: {parsed.get('subject', '')}",
                        html=(
                            "We received your email but hit a temporary capacity issue on our end. "
                            "Please resend in a few minutes and we'll pick it up right away. "
                            "Sorry for the inconvenience."
                        ),
                    ), resend_key)
                except Exception:
                    logger.exception("Failed to send overload notice")
        else:
            raise

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}
