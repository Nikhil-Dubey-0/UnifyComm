"""The only way out for outbound messages (ARCHITECTURE §6.3, CLAUDE.md rule 3).

Every outbound message is inserted as `checking`, passes the compliance engine, and only
then is queued for the worker's `deliver_message` job.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
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
    """Agent reply from the conversation composer. Owns the unit of work (commits)."""
    now = now or datetime.now(UTC)

    replay = await _replay(session, idempotency_key, conversation_id)
    if replay is not None:
        return replay

    conversation = await conversations.get(session, conversation_id, lock=True)
    draft = await _draft(session, draft_id, conversation_id)
    route = await _route(session, conversation.customer_id, channel, settings)
    purpose = (
        Purpose.service_reply
        if conversation.last_inbound_at and conversation.last_inbound_at > now - SERVICE_WINDOW
        else Purpose.proactive
    )

    message_id = await session.scalar(
        insert(Message)
        .values(
            conversation_id=conversation.id,
            channel=channel,
            provider=route.provider,
            direction=Direction.outbound,
            sender_type=SenderType.agent,
            agent_id=agent.id,
            body=body,
            purpose=purpose,
            delivery_status=DeliveryStatus.checking,
            idempotency_key=idempotency_key,
            draft_id=draft.id if draft else None,
            meta={"to": route.to},
        )
        .on_conflict_do_nothing(
            index_elements=["idempotency_key"],
            index_where=Message.idempotency_key.is_not(None),
        )
        .returning(Message.id)
    )
    if message_id is None:
        # A concurrent request with the same key won the insert.
        await session.rollback()
        replay = await _replay(session, idempotency_key, conversation_id)
        if replay is None:  # pragma: no cover - the conflicting row must exist
            raise RuntimeError("idempotency conflict without a stored message")
        return replay

    message = await session.get_one(Message, message_id)
    ctx = await _context(
        session, conversation.customer_id, channel, purpose, body, route, settings, now
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
        if conversation.status == ConversationStatus.open:
            conversation.status = ConversationStatus.pending
        conversation.last_outbound_at = now
        conversation.last_activity_at = now
        if conversation.first_response_at is None:
            conversation.first_response_at = now
        if draft is not None:
            draft.outcome = (
                DraftOutcome.sent_as_is
                if draft.body.strip() == body.strip()
                else DraftOutcome.edited
            )
        await events.emit(session, EventType.conversation_updated, conversation_id=conversation.id)

    await events.emit(
        session, EventType.message_created, conversation_id=conversation.id, message_id=message.id
    )
    await session.commit()
    log.info(
        "outbound message checked",
        extra={
            "message_id": message.id,
            "conversation_id": conversation.id,
            "allowed": decision.allowed,
            "purpose": str(purpose),
        },
    )
    return SendOutcome(message=message, allowed=decision.allowed, checks=checks)


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


async def _replay(
    session: AsyncSession, idempotency_key: str, conversation_id: int
) -> SendOutcome | None:
    message = await session.scalar(
        select(Message).where(Message.idempotency_key == idempotency_key)
    )
    if message is None:
        return None
    if message.conversation_id != conversation_id:
        raise Conflict(
            "This Idempotency-Key was already used for another conversation.",
            code="idempotency_key_reused",
        )
    checks = list(
        await session.scalars(
            select(ComplianceCheck)
            .where(ComplianceCheck.message_id == message.id)
            .order_by(ComplianceCheck.id)
        )
    )
    allowed = message.delivery_status not in (DeliveryStatus.blocked, DeliveryStatus.checking)
    return SendOutcome(message=message, allowed=allowed, checks=checks)


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
