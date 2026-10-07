"""Customer reads, channel preferences, and the manual link of an unverified sender
(ARCHITECTURE §6.6)."""

from datetime import UTC, datetime

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import Channel, Consent
from app.errors import Conflict, NotFound
from app.models import (
    Agent,
    AuditLog,
    ChannelPreference,
    Conversation,
    Customer,
    CustomerContact,
)
from app.schemas.common import Page
from app.schemas.conversations import ConversationOut
from app.schemas.customers import (
    ContactOut,
    CustomerDetail,
    CustomerOut,
    CustomerWithContacts,
    PreferenceOut,
)
from app.services import events
from app.services.events import EventType


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


async def list_customers(
    session: AsyncSession, *, q: str | None, cursor: int | None, limit: int
) -> Page[CustomerWithContacts]:
    stmt = select(Customer).order_by(Customer.id).limit(limit + 1)
    if q:
        pattern = _like(q)
        stmt = stmt.where(
            or_(
                Customer.display_name.ilike(pattern),
                exists().where(
                    CustomerContact.customer_id == Customer.id,
                    CustomerContact.value_normalized.ilike(pattern),
                ),
            )
        )
    if cursor is not None:
        stmt = stmt.where(Customer.id > cursor)
    customers = list(await session.scalars(stmt))
    page, more = customers[:limit], len(customers) > limit

    contacts: dict[int, list[CustomerContact]] = {c.id: [] for c in page}
    preferences: dict[int, list[ChannelPreference]] = {c.id: [] for c in page}
    if page:
        for contact in await session.scalars(
            select(CustomerContact)
            .where(CustomerContact.customer_id.in_(contacts))
            .order_by(CustomerContact.id)
        ):
            contacts[contact.customer_id].append(contact)
        for pref in await session.scalars(
            select(ChannelPreference)
            .where(ChannelPreference.customer_id.in_(preferences))
            .order_by(ChannelPreference.channel)
        ):
            preferences[pref.customer_id].append(pref)

    items = [
        CustomerWithContacts(
            **CustomerOut.model_validate(c).model_dump(),
            contacts=[ContactOut.model_validate(x) for x in contacts[c.id]],
            preferences=[PreferenceOut.model_validate(p) for p in preferences[c.id]],
        )
        for c in page
    ]
    return Page[CustomerWithContacts](items=items, next_cursor=str(page[-1].id) if more else None)


async def customer_detail(session: AsyncSession, customer_id: int) -> CustomerDetail:
    customer = await session.get(Customer, customer_id)
    if customer is None:
        raise NotFound(f"Customer {customer_id} not found.")
    contacts = await session.scalars(
        select(CustomerContact)
        .where(CustomerContact.customer_id == customer_id)
        .order_by(CustomerContact.id)
    )
    preferences = await session.scalars(
        select(ChannelPreference)
        .where(ChannelPreference.customer_id == customer_id)
        .order_by(ChannelPreference.channel)
    )
    conversations = await session.scalars(
        select(Conversation)
        .where(Conversation.customer_id == customer_id)
        .order_by(Conversation.last_activity_at.desc())
    )
    return CustomerDetail(
        customer=CustomerOut.model_validate(customer),
        contacts=[ContactOut.model_validate(c) for c in contacts],
        preferences=[PreferenceOut.model_validate(p) for p in preferences],
        conversations=[ConversationOut.model_validate(c) for c in conversations],
    )


async def link(session: AsyncSession, *, target_id: int, source_id: int, actor: Agent) -> Customer:
    """Merge an unverified source customer into the target. Never automatic. Commits."""
    if target_id == source_id:
        raise Conflict("A customer cannot be linked to itself.", code="same_customer")
    # Lock both rows in id order to avoid deadlocks with a concurrent reverse link.
    locked = {
        c.id: c
        for c in await session.scalars(
            select(Customer)
            .where(Customer.id.in_([target_id, source_id]))
            .order_by(Customer.id)
            .with_for_update()
        )
    }
    target, source = locked.get(target_id), locked.get(source_id)
    if target is None:
        raise NotFound(f"Customer {target_id} not found.")
    if source is None:
        raise NotFound(f"Customer {source_id} not found.")
    if source.verified:
        raise Conflict("Only unverified customers can be linked.", code="source_verified")

    moved_contacts = (
        (
            await session.execute(
                update(CustomerContact)
                .where(CustomerContact.customer_id == source_id)
                .values(customer_id=target_id)
                .returning(CustomerContact.id)
            )
        )
        .scalars()
        .all()
    )
    moved_conversations = (
        (
            await session.execute(
                update(Conversation)
                .where(Conversation.customer_id == source_id)
                .values(customer_id=target_id)
                .returning(Conversation.id)
            )
        )
        .scalars()
        .all()
    )
    # The target's own preferences win; the source's are dropped with the source row.
    await session.execute(delete(Customer).where(Customer.id == source_id))

    session.add(
        AuditLog(
            actor_agent_id=actor.id,
            action="customer.link",
            target_type="customer",
            target_id=target_id,
            details={
                "source_customer_id": source_id,
                "source_display_name": source.display_name,
                "moved_contact_ids": list(moved_contacts),
                "moved_conversation_ids": list(moved_conversations),
            },
        )
    )
    for conversation_id in moved_conversations:
        await events.emit(session, EventType.conversation_updated, conversation_id=conversation_id)
    await session.commit()
    await session.refresh(target)
    return target


async def update_preference(
    session: AsyncSession,
    customer_id: int,
    *,
    channel: Channel,
    consent: Consent,
    dnd: bool,
    actor: Agent,
) -> ChannelPreference:
    """Upsert one channel's consent and DND flag, with an audit entry. Commits."""
    customer = await session.get(Customer, customer_id, with_for_update=True)
    if customer is None:
        raise NotFound(f"Customer {customer_id} not found.")
    before = await session.get(ChannelPreference, (customer_id, str(channel)))
    previous = {"consent": before.consent, "dnd": before.dnd} if before else None
    now = datetime.now(UTC)
    values = {"consent": consent, "dnd": dnd, "updated_at": now, "updated_by": actor.id}
    await session.execute(
        insert(ChannelPreference)
        .values(customer_id=customer_id, channel=channel, **values)
        .on_conflict_do_update(index_elements=["customer_id", "channel"], set_=values)
    )
    session.add(
        AuditLog(
            actor_agent_id=actor.id,
            action="preferences.update",
            target_type="customer",
            target_id=customer_id,
            details={
                "channel": str(channel),
                "before": previous,
                "after": {"consent": str(consent), "dnd": dnd},
            },
        )
    )
    await session.commit()
    pref = await session.get_one(
        ChannelPreference, (customer_id, str(channel)), populate_existing=True
    )
    return pref
