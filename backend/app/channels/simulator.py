"""Simulator provider: emulates WhatsApp, SMS and email (ARCHITECTURE §9.2).

Outbound messages are "delivered" immediately; the simulator page reads them back
through GET /api/simulator/thread.
"""

import uuid
from typing import Any

from app.channels.base import InboundMessage, OutboundMessage, SendResult
from app.enums import CONTACT_KIND_FOR_CHANNEL, Channel, Provider


class SimulatorAdapter:
    provider = Provider.simulator
    channels = {Channel.whatsapp, Channel.sms, Channel.email}

    async def send(self, msg: OutboundMessage) -> SendResult:
        return SendResult(ok=True, external_id=f"sim-out-{msg.message_id}", delivered=True)


def parse_inbound(
    *,
    channel: Channel,
    sender: str,
    body: str,
    sender_name: str | None = None,
    subject: str | None = None,
    external_id: str | None = None,
) -> InboundMessage:
    metadata: dict[str, Any] = {}
    if subject:
        metadata["subject"] = subject
    return InboundMessage(
        channel=channel,
        provider=Provider.simulator,
        external_id=external_id or f"sim-{uuid.uuid4().hex}",
        sender_kind=CONTACT_KIND_FOR_CHANNEL[channel].value,
        sender_raw=sender,
        sender_name=sender_name,
        body=body,
        metadata=metadata,
    )
