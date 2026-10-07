"""The only way out for outbound messages (ARCHITECTURE §6.3, CLAUDE.md rule 3).

Every outbound message (agent reply, proactive outreach, acknowledgement template) is
inserted as `checking`, passes the compliance engine, and only then is queued for the
worker's `deliver_message` job. A blocked message is a recorded event, not an error.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import OutboundMessage
from app.channels.registry import AdapterRegistry
from app.compliance import engine
from app.compliance.engine import Rule, SendContext
from app.config import Settings
from app.enums import (
    CONTACT_KIND_FOR_CHANNEL,
    Channel,
    Consent,
    ConversationStatus,
    DeliveryStatus,
    Direction,
    DraftOutcome,
    JobKind,
    Provider,
    Purpose,
    SenderType,
)
from app.errors import Conflict, NotFound, Unprocessable
from app.models import (
    Agent,
    ChannelPreference,
    ComplianceCheck,
    Conversation,
    Customer,
    CustomerContact,
    Message,
    ReplyDraft,
)
from app.services import conversations, events, jobs
from app.services.events import EventType

log = logging.getLogger(__name__)

SERVICE_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class SendOutcome:
    message: Message
    allowed: bool
    checks: list[ComplianceCheck]


@dataclass(frozen=True)
class Route:
    provider: Provider
    to: str
    last_inbound_at: datetime | None


class DeliveryError(Exception):
    """A retryable provider failure; the job queue retries with backoff."""


def acknowledgement_key(conversation_id: int) -> str:
    """One acknowledgement per conversation, enforced by the idempotency_key index."""
    return f"ack-{conversation_id}"


async def send_agent_reply(
    session: AsyncSession,
    *,
    conversation_id: int,
    agent: Agent,
    channel: Channel,
    body: str,
    idempotency_key: str,
    draft_id: int | None,
    settings: Settings,
    rules: Sequence[Rule],
    now: datetime | None = None,
) -> SendOutcome:
    """Agent reply from the conversation composer (§7.6.1). Owns the unit of work."""
    now = now or datetime.now(UTC)

    replay = await _replay(session, idempotency_key)
    if replay is not None:
        if replay.message.conversation_id != conversation_id:
            raise _key_reused()
        return replay

    conversation = await conversations.get(session, conversation_id, lock=True)
    draft = await _draft(session, draft_id, conversation_id)
    route = await _route(session, conversation.customer_id, channel, settings)
    purpose = (
        Purpose.service_reply
        if conversation.last_inbound_at and conversation.last_inbound_at > now - SERVICE_WINDOW
        else Purpose.proactive
    )
    outcome = await _submit(
        session,
        conversation=conversation,
        channel=channel,
        body=body,
        purpose=purpose,
        sender_type=SenderType.agent,
        agent_id=agent.id,
        idempotency_key=idempotency_key,
        draft=draft,
        route=route,
        settings=settings,
        rules=rules,
        now=now,
    )
    return outcome or await _replay_after_conflict(session, idempotency_key)


async def send_outreach(
    session: AsyncSession,
    *,
    customer_id: int,
    agent: Agent,
    channel: Channel,
    body: str,
    idempotency_key: str,
    settings: Settings,
    rules: Sequence[Rule],
    now: datetime | None = None,
) -> SendOutcome:
    """POST /customers/{id}/outreach: always `proactive` (§7.6.1). Joins the customer's
    active conversation or starts one in `pending` (waiting on the customer). Owns the
    unit of work."""
    now = now or datetime.now(UTC)

    replay = await _replay(session, idempotency_key)
    if replay is not None:
        owner = await session.scalar(
            select(Conversation.customer_id).where(
                Conversation.id == replay.message.conversation_id
            )
        )
        if owner != customer_id:
            raise _key_reused()
        return replay

    if await session.get(Customer, customer_id) is None:
        raise NotFound(f"Customer {customer_id} not found.")
    route = await _route(session, customer_id, channel, settings)
    conversation, created = await conversations.match_or_create(
        session, customer_id, now=now, reopen_days=settings.conversation_reopen_days
    )
    if created:
        conversation.status = ConversationStatus.pending
        await events.emit(session, EventType.conversation_created, conversation_id=conversation.id)
    outcome = await _submit(
        session,
        conversation=conversation,
        channel=channel,
        body=body,
        purpose=Purpose.proactive,
        sender_type=SenderType.agent,
        agent_id=agent.id,
        idempotency_key=idempotency_key,
        draft=None,
        route=route,
        settings=settings,
        rules=rules,
        now=now,
    )
    return outcome or await _replay_after_conflict(session, idempotency_key)


async def send_acknowledgement(
    session: AsyncSession,
    *,
    conversation_id: int,
    body: str,
    channel: Channel,
    settings: Settings,
    rules: Sequence[Rule],
    now: datetime | None = None,
    meta: dict[str, Any] | None = None,
) -> SendOutcome | None:
    """Worker job `send_acknowledgement`: the fixed template (D13), a `service_reply`
    from `system`. Idempotent through acknowledgement_key. The caller commits."""
    now = now or datetime.now(UTC)
    key = acknowledgement_key(conversation_id)
    if await _replay(session, key) is not None:
        return None
    conversation = await conversations.get(session, conversation_id, lock=True)
    route = await _route(session, conversation.customer_id, channel, settings)
    return await _submit(
        session,
        conversation=conversation,
        channel=channel,
        body=body,
        purpose=Purpose.service_reply,
        sender_type=SenderType.system,
        agent_id=None,
        idempotency_key=key,
        draft=None,
        route=route,
        settings=settings,
        rules=rules,
        now=now,
        is_template=True,
        meta=meta,
        commit=False,
    )


async def _submit(
    session: AsyncSession,
    *,
    conversation: Conversation,
    channel: Channel,
    body: str,
    purpose: Purpose,
    sender_type: SenderType,
    agent_id: int | None,
    idempotency_key: str,
    draft: ReplyDraft | None,
    route: Route,
    settings: Settings,
    rules: Sequence[Rule],
    now: datetime,
    is_template: bool = False,
    meta: dict[str, Any] | None = None,
    commit: bool = True,
) -> SendOutcome | None:
    """Insert as `checking`, evaluate every rule, store the checks, then block or queue.

    Returns None when a concurrent request with the same idempotency key won the insert
    (the session is rolled back).
    """
    message_id = await session.scalar(
        insert(Message)
        .values(
            conversation_id=conversation.id,
            channel=channel,
            provider=route.provider,
            direction=Direction.outbound,
            sender_type=sender_type,
            agent_id=agent_id,
            body=body,
            is_template=is_template,
            purpose=purpose,
            delivery_status=DeliveryStatus.checking,
            idempotency_key=idempotency_key,
            draft_id=draft.id if draft else None,
            meta={**(meta or {}), "to": route.to},
        )
        .on_conflict_do_nothing(
            index_elements=["idempotency_key"],
            index_where=Message.idempotency_key.is_not(None),
        )
        .returning(Message.id)
    )
    if message_id is None:
        await session.rollback()
        return None

    message = await session.get_one(Message, message_id)
    ctx = await _context(
        session,
        conversation.customer_id,
        channel,
        purpose,
        body,
        route,
        settings,
        now,
        is_template=is_template,
    )
    decision = engine.evaluate(ctx, rules)
    checks = [
        ComplianceCheck(
            message_id=message.id,
            rule_id=r.rule_id,
            passed=r.passed,
            reason=r.reason,
            context=ctx.audit_context(),
            evaluated_at=now,
        )
        for r in decision.results
    ]
    session.add_all(checks)

    if not decision.allowed:
        message.delivery_status = DeliveryStatus.blocked
    else:
        message.delivery_status = DeliveryStatus.queued
        await jobs.enqueue(session, JobKind.deliver_message, {"message_id": message.id})
        conversation.last_outbound_at = now
        conversation.last_activity_at = now
        if sender_type == SenderType.agent:
            _after_agent_message(conversation, now)
            await _settle_drafts(session, conversation.id, draft, body)
        await events.emit(session, EventType.conversation_updated, conversation_id=conversation.id)

    await events.emit(
        session, EventType.message_created, conversation_id=conversation.id, message_id=message.id
    )
    await session.flush()
    if commit:
        await session.commit()
    log.info(
        "outbound message checked",
        extra={
            "message_id": message.id,
            "conversation_id": conversation.id,
            "allowed": decision.allowed,
            "purpose": str(purpose),
            "sender_type": str(sender_type),
        },
    )
    return SendOutcome(message=message, allowed=decision.allowed, checks=checks)


def _after_agent_message(conversation: Conversation, now: datetime) -> None:
    """§5.3: an agent message moves an open conversation to pending. First response
    time is measured only for conversations the customer started."""
    if conversation.status == ConversationStatus.open:
        conversation.status = ConversationStatus.pending
    if conversation.first_response_at is None and conversation.last_inbound_at is not None:
        conversation.first_response_at = now


async def _settle_drafts(
    session: AsyncSession, conversation_id: int, used: ReplyDraft | None, body: str
) -> None:
    """Record the used draft's outcome; other pending drafts were not used (discarded)."""
    if used is not None:
        used.outcome = (
            DraftOutcome.sent_as_is if used.body.strip() == body.strip() else DraftOutcome.edited
        )
    stmt = update(ReplyDraft).where(
        ReplyDraft.conversation_id == conversation_id,
        ReplyDraft.outcome == DraftOutcome.pending,
    )
    if used is not None:
        stmt = stmt.where(ReplyDraft.id != used.id)
    await session.execute(stmt.values(outcome=DraftOutcome.discarded))


def _key_reused() -> Conflict:
    return Conflict(
        "This Idempotency-Key was already used for another message.",
        code="idempotency_key_reused",
    )


async def _replay(session: AsyncSession, idempotency_key: str) -> SendOutcome | None:
    message = await session.scalar(
        select(Message).where(Message.idempotency_key == idempotency_key)
    )
    if message is None:
        return None
    checks = list(
        await session.scalars(
            select(ComplianceCheck)
            .where(ComplianceCheck.message_id == message.id)
            .order_by(ComplianceCheck.id)
        )
    )
    allowed = message.delivery_status not in (DeliveryStatus.blocked, DeliveryStatus.checking)
    return SendOutcome(message=message, allowed=allowed, checks=checks)


async def _replay_after_conflict(session: AsyncSession, idempotency_key: str) -> SendOutcome:
    replay = await _replay(session, idempotency_key)
    if replay is None:  # pragma: no cover - the conflicting row must exist
        raise RuntimeError("idempotency conflict without a stored message")
    return replay


async def deliver(session: AsyncSession, message_id: int, registry: AdapterRegistry) -> None:
    """Worker job `deliver_message`. Idempotent: does nothing unless the message is queued."""
    message = await session.get(Message, message_id, with_for_update=True)
    if message is None or message.delivery_status != DeliveryStatus.queued:
        return
    adapter = registry.get(Provider(message.provider))
    result = await adapter.send(
        OutboundMessage(
            message_id=message.id,
            channel=Channel(message.channel),
            to=message.meta["to"],
            body=message.body,
            is_template=message.is_template,
            metadata=message.meta,
        )
    )
    if result.ok:
        message.delivery_status = (
            DeliveryStatus.delivered if result.delivered else DeliveryStatus.sent
        )
        message.external_message_id = result.external_id
        message.delivery_error = None
    elif result.retryable:
        raise DeliveryError(result.error or "provider error")
    else:
        message.delivery_status = DeliveryStatus.failed
        message.delivery_error = result.error
    await events.emit(
        session,
        EventType.message_status_changed,
        conversation_id=message.conversation_id,
        message_id=message.id,
    )


async def mark_delivery_failed(session: AsyncSession, message_id: int, error: str) -> None:
    """Called when `deliver_message` has used all its attempts."""
    message = await session.get(Message, message_id, with_for_update=True)
    if message is None or message.delivery_status != DeliveryStatus.queued:
        return
    message.delivery_status = DeliveryStatus.failed
    message.delivery_error = error
    await events.emit(
        session,
        EventType.message_status_changed,
        conversation_id=message.conversation_id,
        message_id=message.id,
    )


async def retry_delivery(session: AsyncSession, message_id: int) -> int:
    """Agent retry of a failed delivery. Commits; returns the job id."""
    message = await session.get(Message, message_id, with_for_update=True)
    if message is None:
        raise NotFound(f"Message {message_id} not found.")
    if message.delivery_status != DeliveryStatus.failed:
        raise Conflict("Only failed deliveries can be retried.", code="not_failed")
    message.delivery_status = DeliveryStatus.queued
    message.delivery_error = None
    job_id = await jobs.enqueue(session, JobKind.deliver_message, {"message_id": message.id})
    await events.emit(
        session,
        EventType.message_status_changed,
        conversation_id=message.conversation_id,
        message_id=message.id,
    )
    await session.commit()
    return job_id


async def _draft(
    session: AsyncSession, draft_id: int | None, conversation_id: int
) -> ReplyDraft | None:
    if draft_id is None:
        return None
    draft = await session.get(ReplyDraft, draft_id)
    if draft is None or draft.conversation_id != conversation_id:
        raise Unprocessable(
            f"Draft {draft_id} does not belong to this conversation.", code="invalid_draft"
        )
    return draft


async def _route(
    session: AsyncSession, customer_id: int, channel: Channel, settings: Settings
) -> Route:
    """§9.3: reply through the provider and address of the customer's latest inbound on
    this channel; otherwise the default provider and the customer's contact."""
    last = (
        await session.execute(
            select(Message.provider, Message.meta["from"].astext, Message.created_at)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.customer_id == customer_id,
                Message.channel == channel,
                Message.direction == Direction.inbound,
            )
            .order_by(Message.id.desc())
            .limit(1)
        )
    ).first()
    if last is not None and last[1]:
        return Route(provider=Provider(last[0]), to=last[1], last_inbound_at=last[2])

    contact = await session.scalar(
        select(CustomerContact)
        .where(
            CustomerContact.customer_id == customer_id,
            CustomerContact.kind == CONTACT_KIND_FOR_CHANNEL[channel],
        )
        .order_by(CustomerContact.verified.desc(), CustomerContact.id)
        .limit(1)
    )
    if contact is None:
        raise Unprocessable(
            f"The customer has no contact for {channel}.", code="no_contact_for_channel"
        )
    return Route(
        provider=settings.default_provider(channel),
        to=contact.value_normalized,
        last_inbound_at=None,
    )


async def _context(
    session: AsyncSession,
    customer_id: int,
    channel: Channel,
    purpose: Purpose,
    body: str,
    route: Route,
    settings: Settings,
    now: datetime,
    *,
    is_template: bool = False,
) -> SendContext:
    pref = await session.get(ChannelPreference, (customer_id, str(channel)))
    return SendContext(
        channel=channel,
        purpose=purpose,
        is_template=is_template,
        body=body,
        consent=Consent(pref.consent) if pref else Consent.unknown,
        dnd=pref.dnd if pref else False,
        now_local=now.astimezone(ZoneInfo(settings.business_timezone)),
        last_inbound_on_channel_at=route.last_inbound_at,
    )
