from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import Channel, Consent, ContactKind
from app.schemas.conversations import ConversationOut


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: ContactKind
    value_normalized: str
    verified: bool
    created_at: datetime


class PreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel: Channel
    consent: Consent
    dnd: bool
    updated_at: datetime
    updated_by: int | None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    verified: bool
    created_at: datetime
    updated_at: datetime


class CustomerWithContacts(CustomerOut):
    contacts: list[ContactOut]
    preferences: list[PreferenceOut]


class CustomerDetail(BaseModel):
    customer: CustomerOut
    contacts: list[ContactOut]
    preferences: list[PreferenceOut]
    conversations: list[ConversationOut]


class LinkRequest(BaseModel):
    source_customer_id: int


class PreferenceUpdate(BaseModel):
    channel: Channel
    consent: Consent
    dnd: bool


class OutreachRequest(BaseModel):
    channel: Channel
    body: str = Field(max_length=100_000)
