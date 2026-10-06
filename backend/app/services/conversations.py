"""Conversation matching (ARCHITECTURE §7.2) and agent-driven updates."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ConversationStatus
from app.errors import Conflict, NotFound, Unprocessable
from app.models import Agent, AuditLog, Conversation, Customer
from app.services import events
from app.services.events import EventType

ACTIVE_STATUSES = (ConversationStatus.open, ConversationStatus.pending)

# Agent-driven transitions (ARCHITECTURE §5.3). Inbound/outbound transitions happen in
# ingest and outbound, not here.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ConversationStatus.open: {ConversationStatus.pending, ConversationStatus.resolved},
    ConversationStatus.pending: {ConversationStatus.open, ConversationStatus.resolved},
    ConversationStatus.resolved: {ConversationStatus.closed},
    ConversationStatus.closed: set(),
}


async def match_or_create(
    session: AsyncSession, customer_id: int, *, now: datetime, reopen_days: int
) -> tuple[Conversation, bool]:
    """Join the customer's latest active conversation on any channel, or start a new one.

    The customer row is locked first so two simultaneous messages from one customer
    cannot create two conversations.
    """
    await session.execute(select(Customer.id).where(Customer.id == customer_id).with_for_update())
    conversation = await session.scalar(
        select(Conversation)
        .where(
            Conversation.customer_id == customer_id,
            Conversation.status.in_(ACTIVE_STATUSES),
            Conversation.last_activity_at > now - timedelta(days=reopen_days),
        )
        .order_by(Conversation.last_activity_at.desc(), Conversation.id.desc())
        .limit(1)
        .with_for_update()
    )
    if conversation is not None:
        return conversation, False

    conversation = Conversation(
        customer_id=customer_id, status=ConversationStatus.open, last_activity_at=now
    )
    session.add(conversation)
    await session.flush()
    return conversation, True


async def get(session: AsyncSession, conversation_id: int, *, lock: bool = False) -> Conversation:
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    if lock:
        stmt = stmt.with_for_update()
    conversation = await session.scalar(stmt)
    if conversation is None:
        raise NotFound(f"Conversation {conversation_id} not found.")
    return conversation


_UNSET = object()


async def update_conversation(
    session: AsyncSession,
    conversation_id: int,
    *,
    actor: Agent,
    status: ConversationStatus | None = None,
    assignee_id: int | None | object = _UNSET,
) -> Conversation:
    """Agent PATCH: status transition and/or (un)assignment. Commits."""
    conversation = await get(session, conversation_id, lock=True)
    changes: dict[str, list] = {}

    if status is not None and status != conversation.status:
        if status not in ALLOWED_TRANSITIONS[ConversationStatus(conversation.status)]:
            raise Conflict(
                f"Cannot change a {conversation.status} conversation to {status}.",
                code="invalid_transition",
            )
        changes["status"] = [conversation.status, str(status)]
        conversation.status = status

    if assignee_id is not _UNSET and assignee_id != conversation.assignee_id:
        if assignee_id is not None:
            assignee = await session.get(Agent, assignee_id)
            if assignee is None or not assignee.is_active:
                raise Unprocessable(
                    f"Agent {assignee_id} does not exist or is inactive.", code="invalid_assignee"
                )
        changes["assignee_id"] = [conversation.assignee_id, assignee_id]
        conversation.assignee_id = assignee_id  # type: ignore[assignment]

    if changes:
        session.add(
            AuditLog(
                actor_agent_id=actor.id,
                action="conversation.update",
                target_type="conversation",
                target_id=conversation.id,
                details=changes,
            )
        )
        await events.emit(session, EventType.conversation_updated, conversation_id=conversation.id)
        await session.commit()
        await session.refresh(conversation)
    return conversation
