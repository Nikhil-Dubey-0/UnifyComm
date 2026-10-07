"""The only way in for inbound messages (ARCHITECTURE §6.1, CLAUDE.md rule 3)."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import InboundMessage
from app.config import Settings
from app.enums import ContactKind, ConversationStatus, Direction, JobKind, SenderType
from app.models import Conversation, Message
from app.services import conversations, events, identity, jobs
from app.services.events import EventType

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestResult:
    message_id: int
    conversation_id: int
    customer_id: int
    duplicate: bool


async def ingest(
    session: AsyncSession, inbound: InboundMessage, settings: Settings
) -> IngestResult:
    """Store one inbound message and enqueue its analysis. Owns the unit of work (commits)."""
    now = datetime.now(UTC)
    kind = ContactKind(inbound.sender_kind)
    sender = identity.normalize(kind, inbound.sender_raw)

    resolved = await identity.resolve(session, kind, sender, inbound.sender_name)
    conversation, created = await conversations.match_or_create(
        session, resolved.customer_id, now=now, reopen_days=settings.conversation_reopen_days
    )

    metadata = {"from": sender, **inbound.metadata}
    if inbound.sender_name:
        metadata.setdefault("sender_name", inbound.sender_name)

    message_id = await session.scalar(
        insert(Message)
        .values(
            conversation_id=conversation.id,
            channel=inbound.channel,
            provider=inbound.provider,
            direction=Direction.inbound,
            sender_type=SenderType.customer,
            body=inbound.body,
            external_message_id=inbound.external_id,
            provider_timestamp=inbound.provider_timestamp,
            meta=metadata,
        )
        .on_conflict_do_nothing(
            index_elements=["provider", "external_message_id"],
            index_where=Message.external_message_id.is_not(None),
        )
        .returning(Message.id)
    )
    if message_id is None:
        # Duplicate delivery: discard everything this attempt did and report the original.
        await session.rollback()
        return await _existing(session, inbound)

    conversation.last_inbound_at = now
    conversation.last_activity_at = now
    if conversation.status == ConversationStatus.pending:
        conversation.status = ConversationStatus.open

    await jobs.enqueue(session, JobKind.analyze_message, {"message_id": message_id})
    if created:
        await jobs.enqueue(
            session, JobKind.send_acknowledgement, {"conversation_id": conversation.id}
        )

    await events.emit(
        session, EventType.message_created, conversation_id=conversation.id, message_id=message_id
    )
    await events.emit(
        session,
        EventType.conversation_created if created else EventType.conversation_updated,
        conversation_id=conversation.id,
    )
    await session.commit()
    log.info(
        "inbound message stored",
        extra={
            "message_id": message_id,
            "conversation_id": conversation.id,
            "channel": str(inbound.channel),
            "provider": str(inbound.provider),
            "new_conversation": created,
        },
    )
    return IngestResult(
        message_id=message_id,
        conversation_id=conversation.id,
        customer_id=resolved.customer_id,
        duplicate=False,
    )


async def _existing(session: AsyncSession, inbound: InboundMessage) -> IngestResult:
    row = (
        await session.execute(
            select(Message.id, Message.conversation_id, Conversation.customer_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.provider == inbound.provider,
                Message.external_message_id == inbound.external_id,
            )
        )
    ).one()
    log.info("duplicate inbound ignored", extra={"message_id": row.id})
    return IngestResult(
        message_id=row.id,
        conversation_id=row.conversation_id,
        customer_id=row.customer_id,
        duplicate=True,
    )
