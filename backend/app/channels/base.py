"""Channel adapter interface (ARCHITECTURE §9.1)."""

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.enums import Channel, Provider


class InboundMessage(BaseModel):
    channel: Channel
    provider: Provider
    external_id: str
    sender_kind: Literal["phone", "email"]
    sender_raw: str
    sender_name: str | None = None
    body: str
    provider_timestamp: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OutboundMessage(BaseModel):
    message_id: int
    channel: Channel
    to: str
    body: str
    is_template: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class SendResult(BaseModel):
    ok: bool
    external_id: str | None = None
    error: str | None = None
    retryable: bool = False
    # True when the provider confirms delivery synchronously (the simulator does).
    delivered: bool = False


class ChannelAdapter(Protocol):
    provider: Provider
    channels: set[Channel]

    async def send(self, msg: OutboundMessage) -> SendResult: ...
