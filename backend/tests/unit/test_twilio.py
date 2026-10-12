"""Twilio WhatsApp: signatures, inbound parsing and sending (ARCHITECTURE §9.2.2).
No network: sends go through httpx.MockTransport."""

import httpx
import pytest
from pydantic import SecretStr

from app.channels.base import OutboundMessage
from app.channels.twilio_whatsapp import (
    MEDIA_ONLY_BODY,
    STATUS_MAP,
    TwilioWhatsAppAdapter,
    compute_signature,
    parse_inbound,
    signature_valid,
)
from app.enums import DeliveryStatus

# The example from Twilio's webhook-security documentation.
DOC_URL = "https://mycompany.com/myapp.php?foo=1&bar=2"
DOC_PARAMS = {
    "CallSid": "CA1234567890ABCDE",
    "Caller": "+12349013030",
    "Digits": "1234",
    "From": "+12349013030",
    "To": "+18005551212",
}
DOC_SIGNATURE = "0/KCTR6DLpKmkAf8muzZqo1nDgQ="

INBOUND = {
    "SmsMessageSid": "SM11111111111111111111111111111111",
    "MessageSid": "SM11111111111111111111111111111111",
    "AccountSid": "AC00000000000000000000000000000000",
    "From": "whatsapp:+919876543210",
    "To": "whatsapp:+14155238886",
    "Body": "My payment failed",
    "NumMedia": "0",
    "ProfileName": "Rahul",
    "WaId": "919876543210",
}


def test_signature_matches_twilio_documentation():
    assert compute_signature(DOC_URL, DOC_PARAMS, "12345") == DOC_SIGNATURE
    assert signature_valid(DOC_URL, DOC_PARAMS, DOC_SIGNATURE, "12345")


@pytest.mark.parametrize(
    "url,params,signature,token",
    [
        (DOC_URL, {**DOC_PARAMS, "Digits": "9999"}, DOC_SIGNATURE, "12345"),  # tampered
        (DOC_URL.replace("https", "http"), DOC_PARAMS, DOC_SIGNATURE, "12345"),  # other URL
        (DOC_URL, DOC_PARAMS, DOC_SIGNATURE, "wrong"),
        (DOC_URL, DOC_PARAMS, DOC_SIGNATURE, ""),  # no token configured
        (DOC_URL, DOC_PARAMS, None, "12345"),  # header missing
    ],
)
def test_invalid_signatures(url, params, signature, token):
    assert not signature_valid(url, params, signature, token)


def test_parse_inbound():
    inbound = parse_inbound(INBOUND)
    assert (inbound.channel, inbound.provider) == ("whatsapp", "twilio")
    assert inbound.external_id == INBOUND["MessageSid"]
    assert (inbound.sender_kind, inbound.sender_raw) == ("phone", "whatsapp:+919876543210")
    assert (inbound.sender_name, inbound.body) == ("Rahul", "My payment failed")
    assert inbound.metadata == {"business_address": "whatsapp:+14155238886"}


def test_media_only_message_gets_a_placeholder():
    inbound = parse_inbound({**INBOUND, "Body": "", "NumMedia": "1", "ProfileName": ""})
    assert inbound.body == MEDIA_ONLY_BODY
    assert inbound.metadata == {"business_address": "whatsapp:+14155238886", "num_media": 1}
    assert inbound.sender_name is None


def test_status_map():
    assert STATUS_MAP["read"] == DeliveryStatus.delivered
    assert STATUS_MAP["undelivered"] == DeliveryStatus.failed
    assert "queued" not in STATUS_MAP and "sending" not in STATUS_MAP


def adapter(settings, handler, public_url="https://demo.trycloudflare.com"):
    configured = settings.model_copy(
        update={
            "twilio_account_sid": "AC123",
            "twilio_auth_token": SecretStr("token"),
            "public_base_url": public_url,
        }
    )
    return TwilioWhatsAppAdapter(configured, transport=httpx.MockTransport(handler))


OUT = OutboundMessage(message_id=5, channel="whatsapp", to="+919876543210", body="Hello")


async def test_send_posts_to_the_messages_api(settings):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["form"] = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(201, json={"sid": "SM999", "status": "queued"})

    result = await adapter(settings, handler).send(OUT)
    assert result.ok and result.external_id == "SM999" and not result.delivered
    assert seen["url"] == "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json"
    assert seen["auth"].startswith("Basic ")
    assert seen["form"] == {
        "From": "whatsapp:+14155238886",
        "To": "whatsapp:+919876543210",
        "Body": "Hello",
        "StatusCallback": "https://demo.trycloudflare.com/api/webhooks/twilio/status",
    }


async def test_no_status_callback_without_public_url(settings):
    seen = {}

    def handler(request):
        seen["form"] = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(201, json={"sid": "SM1"})

    await adapter(settings, handler, public_url="").send(OUT)
    assert "StatusCallback" not in seen["form"]


@pytest.mark.parametrize(
    "status,payload,retryable,error",
    [
        (
            400,
            {"code": 63016, "message": "Outside the allowed window."},
            False,
            "Twilio 63016: Outside the allowed window.",
        ),
        (401, {"code": 20003, "message": "Authenticate"}, False, "Twilio 20003: Authenticate"),
        (429, {"code": 20429, "message": "Too Many Requests"}, True, "Twilio 20429: Too Many"),
        (503, None, True, "Twilio HTTP 503"),
    ],
)
async def test_send_errors(settings, status, payload, retryable, error):
    def handler(request):
        if payload is None:
            return httpx.Response(status, text="Service Unavailable")
        return httpx.Response(status, json=payload)

    result = await adapter(settings, handler).send(OUT)
    assert not result.ok and result.retryable is retryable
    assert result.error.startswith(error)


async def test_network_error_is_retryable(settings):
    def handler(request):
        raise httpx.ConnectTimeout("timed out")

    result = await adapter(settings, handler).send(OUT)
    assert (result.ok, result.retryable, result.error) == (
        False,
        True,
        "Twilio: ConnectTimeout",
    )


@pytest.mark.parametrize(
    "error,retryable",
    [
        (httpx.ConnectError("refused"), True),  # never reached Twilio
        (httpx.ConnectTimeout("timed out"), True),
        (httpx.ReadTimeout("slow"), False),  # Twilio may have sent it: do not resend
        (httpx.RemoteProtocolError("reset"), False),
    ],
)
async def test_only_errors_before_the_request_arrived_are_retried(settings, error, retryable):
    def handler(request):
        raise error

    result = await adapter(settings, handler).send(OUT)
    assert not result.ok and result.retryable is retryable
