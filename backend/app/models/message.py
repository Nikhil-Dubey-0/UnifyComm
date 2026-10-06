from datetime import datetime
from typing import Any

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import (
    AiStatus,
    AiTask,
    Channel,
    DeliveryStatus,
    Direction,
    Provider,
    Purpose,
    SenderType,
)
from app.models.base import Base, created_at, enum_check, pk


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation", "conversation_id", "id"),
        Index(
            "uq_messages_provider_external_id",
            "provider",
            "external_message_id",
            unique=True,
            postgresql_where=text("external_message_id IS NOT NULL"),
        ),
        Index(
            "uq_messages_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        CheckConstraint(
            "direction <> 'inbound' OR delivery_status IS NULL", name="inbound_no_delivery"
        ),
        enum_check("channel", Channel),
        enum_check("provider", Provider),
        enum_check("direction", Direction),
        enum_check("sender_type", SenderType),
        enum_check("purpose", Purpose, nullable=True),
        enum_check("delivery_status", DeliveryStatus, nullable=True),
    )

    id: Mapped[int] = pk()
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id"), nullable=False
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    sender_type: Mapped[str] = mapped_column(Text, nullable=False)
    agent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("agents.id"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_template: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    purpose: Mapped[str | None] = mapped_column(Text)
    external_message_id: Mapped[str | None] = mapped_column(Text)
    delivery_status: Mapped[str | None] = mapped_column(Text)
    delivery_error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    draft_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("reply_drafts.id", use_alter=True)
    )
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "metadata" is reserved on declarative classes, so the attribute is `meta`.
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = created_at()


class MessageAiResult(Base):
    __tablename__ = "message_ai_results"
    __table_args__ = (
        UniqueConstraint("message_id", "task", name="uq_message_ai_results_message_task"),
        enum_check("task", AiTask),
        enum_check("status", AiStatus),
    )

    id: Mapped[int] = pk()
    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    task: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(REAL())
    top_k: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at()


class ComplianceCheck(Base):
    __tablename__ = "compliance_checks"
    __table_args__ = (Index("ix_compliance_checks_passed_evaluated", "passed", "evaluated_at"),)

    id: Mapped[int] = pk()
    message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("messages.id"), nullable=False, index=True
    )
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
