from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import Channel, DeliveryStatus, Direction, SenderType


class SimulatorInboundRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    channel: Channel
    sender: str = Field(alias="from", min_length=1, max_length=320)
    sender_name: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=50_000)
    subject: str | None = Field(default=None, max_length=500)
    external_id: str | None = Field(default=None, min_length=1, max_length=200)


class SimulatorInboundResponse(BaseModel):
    message_id: int
    conversation_id: int
    customer_id: int
    duplicate: bool


class SimulatorAddresses(BaseModel):
    whatsapp: str | None = None
    sms: str | None = None
    email: str | None = None


class SimulatorContact(BaseModel):
    customer_id: int
    display_name: str
    verified: bool
    addresses: SimulatorAddresses


class SimulatorThreadMessage(BaseModel):
    id: int
    conversation_id: int
    channel: Channel
    direction: Direction
    sender_type: SenderType
    body: str
    subject: str | None
    delivery_status: DeliveryStatus | None
    created_at: datetime
