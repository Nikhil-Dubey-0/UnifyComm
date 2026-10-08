"""Twilio webhooks (ARCHITECTURE §9.2.2). Unauthenticated, so every request must carry a
valid X-Twilio-Signature computed over PUBLIC_BASE_URL + path."""

from fastapi import APIRouter, Request, Response

from app.api.deps import SessionDep, SettingsDep
from app.channels.twilio_whatsapp import (
    EMPTY_TWIML,
    STATUS_MAP,
    parse_inbound,
    signature_valid,
)
from app.config import Settings
from app.enums import Provider
from app.errors import Forbidden, Unprocessable
from app.schemas.common import ERROR_RESPONSES
from app.services import ingest, outbound

router = APIRouter(prefix="/webhooks/twilio", tags=["webhooks"], responses=ERROR_RESPONSES)

TWIML_RESPONSE = {200: {"content": {"text/xml": {}}, "description": "Empty TwiML"}}


async def _verified_form(request: Request, settings: Settings) -> dict[str, str]:
    form = {key: str(value) for key, value in (await request.form()).items()}
    url = settings.public_base_url.rstrip("/") + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    if not settings.public_base_url or not signature_valid(
        url,
        form,
        request.headers.get("X-Twilio-Signature"),
        settings.twilio_auth_token.get_secret_value(),
    ):
        raise Forbidden("Invalid Twilio signature.", code="invalid_signature")
    return form


@router.post("/whatsapp", response_class=Response, responses=TWIML_RESPONSE)
async def whatsapp_inbound(
    request: Request, session: SessionDep, settings: SettingsDep
) -> Response:
    form = await _verified_form(request, settings)
    if not form.get("MessageSid") or not form.get("From"):
        raise Unprocessable("MessageSid and From are required.", code="invalid_webhook")
    await ingest.ingest(session, parse_inbound(form), settings)
    return Response(content=EMPTY_TWIML, media_type="text/xml")


@router.post("/status", response_class=Response, responses={200: {"description": "Accepted"}})
async def message_status(request: Request, session: SessionDep, settings: SettingsDep) -> Response:
    form = await _verified_form(request, settings)
    status = STATUS_MAP.get(form.get("MessageStatus", "").lower())
    sid = form.get("MessageSid")
    if status is not None and sid:
        code = form.get("ErrorCode")
        await outbound.apply_provider_status(
            session,
            provider=Provider.twilio,
            external_id=sid,
            status=status,
            error=f"Twilio {code}" if code else None,
        )
    return Response(status_code=200)
