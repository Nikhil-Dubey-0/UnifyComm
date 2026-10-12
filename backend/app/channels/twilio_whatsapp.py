"""Twilio WhatsApp provider (ARCHITECTURE §9.2.2). No Twilio SDK: the webhook signature
is HMAC-SHA1 and sending is one REST call with httpx.
"""

import base64
import hashlib
import hmac
import logging
from collections.abc import Mapping

import httpx

from app.channels.base import InboundMessage, OutboundMessage, SendResult
from app.config import Settings
from app.enums import Channel, DeliveryStatus, Provider

log = logging.getLogger(__name__)

API_BASE = "https://api.twilio.com/2010-04-01"
SEND_TIMEOUT_SECONDS = 20
STATUS_CALLBACK_PATH = "/api/webhooks/twilio/status"
MEDIA_ONLY_BODY = "[Attachment not supported]"
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'

# Twilio MessageStatus → our delivery status. Absent statuses (queued, accepted,
# sending, scheduled) carry no new information for us.
STATUS_MAP: dict[str, DeliveryStatus] = {
    "sent": DeliveryStatus.sent,
    "delivered": DeliveryStatus.delivered,
    "read": DeliveryStatus.delivered,
    "failed": DeliveryStatus.failed,
    "undelivered": DeliveryStatus.failed,
}


def compute_signature(url: str, params: Mapping[str, str], auth_token: str) -> str:
    """Twilio's webhook signature: url + each POST parameter's key and value, sorted by
    key, HMAC-SHA1 with the auth token, base64."""
    data = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode(), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def signature_valid(
    url: str, params: Mapping[str, str], signature: str | None, auth_token: str
) -> bool:
    if not auth_token or not signature:
        return False
    return hmac.compare_digest(compute_signature(url, params, auth_token), signature)


def whatsapp_address(phone_e164: str) -> str:
    return phone_e164 if phone_e164.startswith("whatsapp:") else f"whatsapp:{phone_e164}"


def parse_inbound(form: Mapping[str, str]) -> InboundMessage:
    """Twilio's inbound WhatsApp webhook form → InboundMessage."""
    num_media = int(form.get("NumMedia", "0") or 0)
    body = (form.get("Body") or "").strip()
    metadata: dict = {}
    if form.get("To"):
        # Our number the customer wrote to: replies must come from it (§9.2.2).
        metadata["business_address"] = form["To"]
    if num_media:
        metadata["num_media"] = num_media
    return InboundMessage(
        channel=Channel.whatsapp,
        provider=Provider.twilio,
        external_id=form["MessageSid"],
        sender_kind="phone",
        sender_raw=form["From"],  # "whatsapp:+91…"; identity.normalize strips the prefix
        sender_name=(form.get("ProfileName") or "").strip() or None,
        body=body or MEDIA_ONLY_BODY,
        metadata=metadata,
    )


class TwilioWhatsAppAdapter:
    provider = Provider.twilio
    channels = {Channel.whatsapp}

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._transport = transport

    async def send(self, msg: OutboundMessage) -> SendResult:
        s = self._settings
        data = {
            # Reply from the number the customer wrote to; Twilio rejects free-form
            # messages from any other sender (21654, ContentSid required).
            "From": msg.metadata.get("business_address") or s.twilio_whatsapp_from,
            "To": whatsapp_address(msg.to),
            "Body": msg.body,
        }
        if s.public_base_url:
            data["StatusCallback"] = s.public_base_url.rstrip("/") + STATUS_CALLBACK_PATH
        url = f"{API_BASE}/Accounts/{s.twilio_account_sid}/Messages.json"
        try:
            async with httpx.AsyncClient(
                timeout=SEND_TIMEOUT_SECONDS, transport=self._transport
            ) as client:
                response = await client.post(
                    url,
                    data=data,
                    auth=(s.twilio_account_sid, s.twilio_auth_token.get_secret_value()),
                )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            # The request never reached Twilio: safe to retry.
            return SendResult(ok=False, error=f"Twilio: {type(exc).__name__}", retryable=True)
        except httpx.HTTPError as exc:
            # Twilio may already have accepted it (Messages has no idempotency key):
            # resending could deliver it twice, so the agent decides (retry button).
            return SendResult(
                ok=False,
                error=f"Twilio: {type(exc).__name__}; the message may have been sent, "
                "check before retrying",
                retryable=False,
            )

        if response.is_success:
            return SendResult(ok=True, external_id=response.json().get("sid"))
        error = _error_text(response)
        retryable = response.status_code == 429 or response.status_code >= 500
        log.warning(
            "twilio send failed",
            extra={"status_code": response.status_code, "retryable": retryable},
        )
        return SendResult(ok=False, error=error, retryable=retryable)


def _error_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"Twilio HTTP {response.status_code}"
    code = payload.get("code")
    message = str(payload.get("message", "")).strip()
    return f"Twilio {code}: {message}"[:300] if code else f"Twilio HTTP {response.status_code}"
