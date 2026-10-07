"""Standalone tables: jobs, audit_log, system_status."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import JobKind, JobStatus
from app.models.base import Base, created_at, enum_check, pk, updated_at


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "ix_jobs_pending",
            "run_after",
            "id",
            postgresql_where=text("status = 'pending'"),
        ),
        # At most one queued summary per conversation (ARCHITECTURE §5.2, §6.5).
        Index(
            "uq_jobs_active_summary",
            text("(payload->>'conversation_id')"),
            unique=True,
            postgresql_where=text(
                "kind = 'summarize_conversation' AND status IN ('pending', 'running')"
            ),
        ),
        enum_check("kind", JobKind),
        enum_check("status", JobStatus),
    )

    id: Mapped[int] = pk()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=JobStatus.pending)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = pk()
    actor_agent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("agents.id"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = created_at()


class SystemStatus(Base):
    __tablename__ = "system_status"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = updated_at()
