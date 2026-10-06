from datetime import datetime
from typing import Any

from sqlalchemy import REAL, BigInteger, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import ConversationStatus, DraftOutcome, Priority
from app.models.base import Base, created_at, enum_check, pk, updated_at


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_customer_activity", "customer_id", "last_activity_at"),
        Index("ix_conversations_inbox", "status", "priority", "last_inbound_at"),
        enum_check("status", ConversationStatus),
        enum_check("priority", Priority),
    )

    id: Mapped[int] = pk()
    customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("customers.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=ConversationStatus.open
    )
    assignee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("agents.id"))
    category: Mapped[str | None] = mapped_column(Text)
    primary_intent: Mapped[str | None] = mapped_column(Text)
    primary_intent_confidence: Mapped[float | None] = mapped_column(REAL())
    priority: Mapped[str] = mapped_column(Text, nullable=False, server_default=Priority.normal)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"
    __table_args__ = (Index("ix_conversation_summaries_conv", "conversation_id", "id"),)

    id: Mapped[int] = pk()
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    key_points: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    covers_until_message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("messages.id"), nullable=False
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at()


class ReplyDraft(Base):
    __tablename__ = "reply_drafts"
    __table_args__ = (enum_check("outcome", DraftOutcome),)

    id: Mapped[int] = pk()
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id"), nullable=False, index=True
    )
    agent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("agents.id"), nullable=False)
    based_on_message_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("messages.id"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    verify_hints: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    model: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False, server_default=DraftOutcome.pending)
    created_at: Mapped[datetime] = created_at()
