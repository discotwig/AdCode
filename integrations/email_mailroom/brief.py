import json
import logging
from pathlib import Path

from integrations.email_mailroom.prompts import BRIEF_EXTRACT
from src.services.ingest import IngestionResult, Ambiguity

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "campaign.schema.json"


def extract_from_text(body: str, ai_client) -> IngestionResult:
    """Extract campaign definitions from a plain-text email body via Claude.

    Returns the same IngestionResult shape as extract_campaigns() in ingest.py.
    """
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    prompt = BRIEF_EXTRACT.format(
        schema=json.dumps(schema, indent=2),
        email_body=body,
    )
    response = ai_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rstrip("`").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Brief extraction returned invalid JSON; raw=%r", raw[:200])
        return IngestionResult(campaigns=[], ambiguities=[], confidence=0.0)

    ambiguities = [
        Ambiguity(
            field=a.get("field", ""),
            sheet=a.get("sheet", ""),
            cell_ref=a.get("cell_ref", ""),
            raw_value=a.get("raw_value", ""),
            question=a.get("question", ""),
        )
        for a in data.get("ambiguities", [])
    ]
    return IngestionResult(
        campaigns=data.get("campaigns", []),
        ambiguities=ambiguities,
        confidence=float(data.get("confidence", 1.0)),
    )
