"""Gmail provider: IMAP inbound parsing and SMTP outbound (ARCHITECTURE §9.2.1).

Parsing and MIME building are pure functions; network calls use the stdlib in worker
threads. Certificates are always verified (Avast re-signs mail TLS on the dev laptop; port
587 STARTTLS verifies, 465 does not).
"""

import asyncio
import email
import html
import logging
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import formataddr, getaddresses, parsedate_to_datetime

from app.channels.base import InboundMessage, OutboundMessage, SendResult
from app.config import Settings
from app.enums import Channel, Provider

log = logging.getLogger(__name__)

MAX_BODY_CHARS = 50_000
SMTP_TIMEOUT_SECONDS = 30
ATTACHMENT_ONLY_BODY = "[Attachment not supported]"

_TAG = re.compile(r"<[^>]+>")
_BLOCK_END = re.compile(r"</(p|div|li|tr|h[1-6])\s*>|<br\s*/?>", re.IGNORECASE)
_DROP = re.compile(r"<(script|style|head)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_BLANK_LINES = re.compile(r"\n\s*\n\s*\n+")
_LINE_BREAKS = re.compile(r"[\r\n]+\s*")
MAX_HEADER_CHARS = 300


def header_text(value: object) -> str:
    """One-line header value. Encoded words can decode to CR/LF; letting those through
    would make every reply in the thread fail (email refuses them) (security review)."""
    return _LINE_BREAKS.sub(" ", str(value or "")).strip()[:MAX_HEADER_CHARS]


class AmbiguousSend(Exception):
    """The connection failed while the message was being handed over: the server may have
    accepted it. Never retried automatically (a duplicate reaches a real customer)."""


@dataclass(frozen=True)
class Skip:
    """A message the poller leaves alone (unread), with the reason for the log."""

    reason: str


def html_to_text(markup: str) -> str:
    text = _DROP.sub("", markup)
    text = _BLOCK_END.sub("\n", text)
    text = html.unescape(_TAG.sub("", text))
    lines = [line.strip() for line in text.splitlines()]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def _text(part: EmailMessage) -> str:
    """Decoded text of a part. An unknown or wrong charset must not stop ingestion, so fall
    back to UTF-8 with replacement characters."""
    try:
        return part.get_content()
    except (LookupError, UnicodeDecodeError):
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def _body(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain",))
    if part is not None:
        text = _text(part)
    else:
        part = msg.get_body(preferencelist=("html",))
        text = html_to_text(_text(part)) if part is not None else ""
    text = text.replace("\r\n", "\n").strip()
    return (text or ATTACHMENT_ONLY_BODY)[:MAX_BODY_CHARS]


def is_automatic(msg: EmailMessage) -> bool:
    """RFC 3834: never acknowledge machine-generated or list mail."""
    auto = str(msg.get("Auto-Submitted", "no")).strip().lower()
    precedence = str(msg.get("Precedence", "")).strip().lower()
    return auto != "no" or precedence in {"bulk", "list", "junk"} or msg.get("List-Id") is not None


def sender_allowed(address: str, allowed: list[str]) -> bool:
    return "*" in allowed or address.lower() in allowed


def parse_email(
    raw: bytes, *, own_address: str, allowed: list[str], fallback_id: str
) -> InboundMessage | Skip:
    """One raw RFC 5322 message → InboundMessage, or Skip (left unread)."""
    msg = email.message_from_bytes(raw, policy=default_policy)
    assert isinstance(msg, EmailMessage)
    senders = getaddresses([str(msg.get("From", ""))])
    if not senders or not senders[0][1]:
        return Skip("no sender")
    name, address = senders[0]
    address = address.strip().lower()
    if address == own_address.strip().lower():
        return Skip("own address")
    if not sender_allowed(address, allowed):
        return Skip("sender not allowlisted")
    if is_automatic(msg):
        return Skip("automatic mail")

    message_id = header_text(msg.get("Message-ID"))
    metadata: dict = {
        "subject": header_text(msg.get("Subject")),
        "message_id": message_id or None,
        "in_reply_to": header_text(msg.get("In-Reply-To")) or None,
        "references": str(msg.get("References", "")).split(),
    }
    sent_at = None
    if msg.get("Date"):
        try:
            sent_at = parsedate_to_datetime(str(msg["Date"]))
        except (TypeError, ValueError):
            sent_at = None
    return InboundMessage(
        channel=Channel.email,
        provider=Provider.gmail,
        external_id=message_id or fallback_id,
        sender_kind="email",
        sender_raw=address,
        sender_name=header_text(name) or None,
        body=_body(msg),
        provider_timestamp=sent_at if sent_at and sent_at.tzinfo else None,
        metadata=metadata,
    )


def build_mime(out: OutboundMessage, *, from_address: str, from_name: str) -> EmailMessage:
    """The outgoing email with threading headers from the message metadata (§9.2.1)."""
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_address))
    msg["To"] = header_text(out.to)
    msg["Subject"] = header_text(out.metadata.get("subject")) or "Your message to our support team"
    # Stable per message: a manual resend keeps the ID, so mail clients can dedupe it.
    msg["Message-ID"] = f"<unifycomm.{out.message_id}@{from_address.split('@')[-1]}>"
    if header_text(out.metadata.get("in_reply_to")):
        msg["In-Reply-To"] = header_text(out.metadata["in_reply_to"])
    references = [header_text(r) for r in out.metadata.get("references") or [] if header_text(r)]
    if references:
        msg["References"] = " ".join(references)
    msg["Auto-Submitted"] = "auto-replied" if out.is_template else "no"
    msg.set_content(out.body)
    return msg


class GmailAdapter:
    provider = Provider.gmail
    channels = {Channel.email}

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, msg: OutboundMessage) -> SendResult:
        mime = build_mime(
            msg,
            from_address=self._settings.email_address,
            from_name=self._settings.email_from_name,
        )
        try:
            await asyncio.to_thread(self._send_sync, mime)
        except AmbiguousSend as exc:
            cause = type(exc.__cause__).__name__
            return SendResult(
                ok=False,
                error=f"SMTP: {cause} while sending; check before retrying",
                retryable=False,
            )
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPAuthenticationError) as exc:
            return SendResult(ok=False, error=f"SMTP: {type(exc).__name__}", retryable=False)
        except smtplib.SMTPResponseException as exc:
            permanent = 500 <= exc.smtp_code < 600
            return SendResult(ok=False, error=f"SMTP {exc.smtp_code}", retryable=not permanent)
        except (smtplib.SMTPException, OSError) as exc:
            return SendResult(ok=False, error=f"SMTP: {type(exc).__name__}", retryable=True)
        return SendResult(ok=True, external_id=str(mime["Message-ID"]))

    def _send_sync(self, mime: EmailMessage) -> None:
        s = self._settings
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(s.email_address, s.email_password)
            try:
                smtp.send_message(mime)
            except smtplib.SMTPResponseException:
                raise  # the server answered: the message was definitely not accepted
            except smtplib.SMTPRecipientsRefused:
                raise
            except (smtplib.SMTPServerDisconnected, OSError) as exc:
                raise AmbiguousSend() from exc
