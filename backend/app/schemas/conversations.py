from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.ai.contracts import LabelScore
from app.ai.intent_map import get_intent_map
from app.enums import (
    AiStatus,
    AiTask,
    Channel,
    ConversationStatus,
    DeliveryStatus,
    Direction,
    DraftOutcome,
    JobStatus,
    Priority,
    Provider,
    Purpose,
    SenderType,
)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    status: ConversationStatus
    assignee_id: int | None
    category: str | None
    primary_intent: str | None
    primary_intent_confidence: float | None
    priority: Priority
    last_inbound_at: datetime | None
    last_outbound_at: datetime | None
    first_response_at: datetime | None
    last_activity_at: datetime
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def category_queue(self) -> str | None:
        """UI queue name for the category (ARCHITECTURE §7.3)."""
        if self.category is None:
            return None
        category = get_intent_map().categories.get(self.category)
        return category.queue if category else None


class CustomerRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    verified: bool


class MessagePreview(BaseModel):
    id: int
    channel: Channel
    direction: Direction
    sender_type: SenderType
    body_preview: str
    created_at: datetime


class ConversationListItem(ConversationOut):
    customer: CustomerRef
    last_message: MessagePreview | None


class AiResultOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    task: AiTask
    status: AiStatus
    label: str | None
    confidence: float | None
    top_k: list[LabelScore] | None
    model_name: str
    model_version: str
    error: str | None
    latency_ms: int | None
    created_at: datetime
    # Intent only: routing view of the label (ARCHITECTURE §7.3).
    category: str | None = None
    category_queue: str | None = None
    needs_review: bool | None = None


class MessageAi(BaseModel):
    """`null` for a task means analysis is still pending."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    intent: AiResultOut | None = None
    sentiment: AiResultOut | None = None


class ComplianceCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: str
    passed: bool
    reason: str | None
    evaluated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    channel: Channel
    provider: Provider
    direction: Direction
    sender_type: SenderType
    agent_id: int | None
    body: str
    is_template: bool
    purpose: Purpose | None
    external_message_id: str | None
    delivery_status: DeliveryStatus | None
    delivery_error: str | None
    draft_id: int | None
    provider_timestamp: datetime | None
    metadata: dict[str, Any] = Field(validation_alias="meta")
    created_at: datetime


class MessageWithAnalysis(MessageOut):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    ai: MessageAi = Field(default_factory=MessageAi)
    compliance_checks: list[ComplianceCheckOut] = Field(default_factory=list)


class SummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    body: str
    key_points: dict[str, Any]
    covers_until_message_id: int
    model: str
    created_at: datetime


class ContactRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    value_normalized: str
    verified: bool


class CustomerWithContactsRef(CustomerRef):
    contacts: list[ContactRef]


class SummaryJobOut(BaseModel):
    job_id: int
    status: JobStatus
    updated_at: datetime


class ConversationDetail(BaseModel):
    conversation: ConversationOut
    customer: CustomerWithContactsRef
    messages: list[MessageWithAnalysis]
    latest_summary: SummaryOut | None
    summary_job: SummaryJobOut | None


class ConversationPatch(BaseModel):
    status: ConversationStatus | None = None
    assignee_id: int | None = None


class SendRequest(BaseModel):
    channel: Channel
    body: str = Field(max_length=100_000)
    draft_id: int | None = None


class ComplianceOut(BaseModel):
    allowed: bool
    results: list[ComplianceCheckOut]


class SendResponse(BaseModel):
    message: MessageOut
    compliance: ComplianceOut


class DraftRequestIn(BaseModel):
    instructions: str | None = Field(default=None, max_length=1_000)
    channel: Channel | None = None


class DraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    based_on_message_id: int
    body: str
    verify_hints: list[str]
    model: str
    outcome: DraftOutcome
    created_at: datetime
