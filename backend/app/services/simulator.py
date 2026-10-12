"""Read side of the customer simulator page (ARCHITECTURE §9.2, §10)."""

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import CONTACT_KIND_FOR_CHANNEL, Channel, ContactKind, Direction, Provider
from app.models import Customer, CustomerContact, Message
from app.schemas.simulator import SimulatorAddresses, SimulatorContact, SimulatorThreadMessage
from app.services import identity

THREAD_LIMIT = 200


RECENT_UNVERIFIED = 30


async def contacts(session: AsyncSession) -> list[SimulatorContact]:
    """Verified customers (seeded or registered), then the most recent unverified senders,
    each with one address per channel. Listing unverified senders lets a sender created in
    the simulator write again on another channel."""
    recent = (
        select(Customer.id)
        .where(Customer.verified.is_(False))
        .order_by(Customer.id.desc())
        .limit(RECENT_UNVERIFIED)
        .scalar_subquery()
    )
    rows = await session.execute(
        select(Customer, CustomerContact)
        .join(CustomerContact, CustomerContact.customer_id == Customer.id)
        .where(Customer.verified.is_(True) | Customer.id.in_(recent))
        .order_by(Customer.verified.desc(), Customer.id, CustomerContact.id)
    )
    result: dict[int, SimulatorContact] = {}
    for customer, contact in rows:
        entry = result.setdefault(
            customer.id,
            SimulatorContact(
                customer_id=customer.id,
                display_name=customer.display_name,
                verified=customer.verified,
                addresses=SimulatorAddresses(),
            ),
        )
        addresses = entry.addresses
        if contact.kind == ContactKind.phone:
            addresses.whatsapp = addresses.whatsapp or contact.value_normalized
            addresses.sms = addresses.sms or contact.value_normalized
        else:
            addresses.email = addresses.email or contact.value_normalized
    verified = [c for c in result.values() if c.verified]
    unverified = sorted(
        (c for c in result.values() if not c.verified), key=lambda c: -c.customer_id
    )
    return verified + unverified


async def thread(
    session: AsyncSession, channel: Channel, address: str
) -> list[SimulatorThreadMessage]:
    """Messages to and from one address on one channel, as the customer sees them."""
    normalized = identity.normalize(CONTACT_KIND_FOR_CHANNEL[channel], address)
    rows = await session.scalars(
        select(Message)
        .where(
            Message.provider == Provider.simulator,
            Message.channel == channel,
            or_(
                and_(
                    Message.direction == Direction.inbound,
                    Message.meta["from"].astext == normalized,
                ),
                and_(
                    Message.direction == Direction.outbound,
                    Message.meta["to"].astext == normalized,
                ),
            ),
        )
        .order_by(Message.id.desc())
        .limit(THREAD_LIMIT)
    )
    return [
        SimulatorThreadMessage(
            id=m.id,
            conversation_id=m.conversation_id,
            channel=m.channel,
            direction=m.direction,
            sender_type=m.sender_type,
            body=m.body,
            subject=m.meta.get("subject"),
            delivery_status=m.delivery_status,
            created_at=m.created_at,
        )
        for m in reversed(list(rows))
    ]
