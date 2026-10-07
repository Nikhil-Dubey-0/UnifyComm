"""Conversation context for LLM calls (ARCHITECTURE §6.4, §6.5, §7.7).

Every text that leaves for the LLM passes `text_prep.redact_pii`. Blocked messages were
never delivered and the acknowledgement is a fixed template, so neither is included.
"""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import text_prep
from app.ai.llm import ContextMessage
from app.enums import DeliveryStatus, Direction
from app.models import ConversationSummary, Message


async def latest_summary(session: AsyncSession, conversation_id: int) -> ConversationSummary | None:
    return await session.scalar(
        select(ConversationSummary)
        .where(ConversationSummary.conversation_id == conversation_id)
        .order_by(ConversationSummary.id.desc())
        .limit(1)
    )


async def context_messages(
    session: AsyncSession, conversation_id: int, *, after_id: int | None = None, limit: int
) -> list[ContextMessage]:
    """The newest `limit` dialogue messages after `after_id`, oldest first, redacted."""
    stmt = (
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.is_template.is_(False),
            or_(
                Message.direction == Direction.inbound,
                Message.delivery_status.not_in([DeliveryStatus.blocked, DeliveryStatus.checking]),
            ),
        )
        .order_by(Message.id.desc())
        .limit(limit)
    )
    if after_id is not None:
        stmt = stmt.where(Message.id > after_id)
    rows = list(await session.scalars(stmt))
    return [
        ContextMessage(
            at=m.created_at,
            author=m.sender_type,
            channel=m.channel,
            body=text_prep.redact_pii(m.body),
        )
        for m in reversed(rows)
    ]


def summary_text(summary: ConversationSummary) -> str:
    """The stored summary as plain text for the draft prompt."""
    points = summary.key_points
    lines = [summary.body]
    if points.get("open_items"):
        lines.append("Open items: " + "; ".join(points["open_items"]))
    return text_prep.redact_pii("\n".join(lines))
