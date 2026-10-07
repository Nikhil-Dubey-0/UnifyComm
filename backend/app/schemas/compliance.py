from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.enums import Channel, DeliveryStatus, Purpose, SenderType


class CheckedMessage(BaseModel):
    id: int
    conversation_id: int
    channel: Channel
    purpose: Purpose | None
    sender_type: SenderType
    delivery_status: DeliveryStatus | None
    is_template: bool


class CheckedCustomer(BaseModel):
    id: int
    display_name: str


class ComplianceLogItem(BaseModel):
    id: int
    rule_id: str
    passed: bool
    reason: str | None
    context: dict[str, Any]
    evaluated_at: datetime
    message: CheckedMessage
    customer: CheckedCustomer
