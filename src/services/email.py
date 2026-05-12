import logging
from dataclasses import dataclass, field

import resend

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    from_: str
    to: str
    subject: str
    html: str
    reply_to: str | None = None
    in_reply_to: str | None = None


def send_email(msg: EmailMessage, api_key: str) -> str:
    """Send an email via Resend. Returns the Resend email ID."""
    resend.api_key = api_key
    params: dict = {
        "from": msg.from_,
        "to": [msg.to],
        "subject": msg.subject,
        "html": msg.html,
    }
    if msg.reply_to:
        params["reply_to"] = msg.reply_to
    if msg.in_reply_to:
        params["headers"] = {"In-Reply-To": msg.in_reply_to}
    response = resend.Emails.send(params)
    email_id = response["id"]
    logger.info("Sent email to=%s subject=%r id=%s", msg.to, msg.subject, email_id)
    return email_id
