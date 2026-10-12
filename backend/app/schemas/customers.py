from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class CustomerCreate(BaseModel):
    """A customer registered by staff (KYC onboarding): phone and/or email, verified."""

    display_name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=320)

    @field_validator("display_name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def _one_contact(self) -> "CustomerCreate":
        if not (self.phone or "").strip() and not (self.email or "").strip():
            raise ValueError("give a phone number, an email address or both")
        return self
