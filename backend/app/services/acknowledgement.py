"""The automatic acknowledgement on a new conversation (ARCHITECTURE D13, §12).

A fixed template, never LLM output. It is a `service_reply` from `system` and passes the
compliance engine like any other outbound message.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance.engine import Rule
from app.config import Settings
from app.enums import Channel, Direction
from app.models import Conversation, Customer, Message
from app.services import outbound

TEMPLATE = (
    "{greeting}, thank you for contacting us. We have received your message and an agent "
    "will reply shortly. Your reference number is #{conversation_id}."
)
EMAIL_SUBJECT = "We have received your message (#{conversation_id})"


def build_body(customer: Customer, conversation_id: int) -> str:
    """Greets verified customers by first name; unknown senders get a neutral greeting."""
    first_name = customer.display_name.split()[0] if customer.display_name.strip() else ""
    greeting = f"Hi {first_name}" if customer.verified and first_name else "Hello"
    return TEMPLATE.format(greeting=greeting, conversation_id=conversation_id)


async def acknowledge(
    session: AsyncSession, conversation_id: int, *, settings: Settings, rules: Sequence[Rule]
) -> None:
    """Job handler body. Replies on the channel of the message that opened the
    conversation. The caller commits."""
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        return
    first_inbound = await session.scalar(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.direction == Direction.inbound)
        .order_by(Message.id)
        .limit(1)
    )
    if first_inbound is None:
        return
    customer = await session.get_one(Customer, conversation.customer_id)
    channel = Channel(first_inbound.channel)
    meta = (
        {"subject": EMAIL_SUBJECT.format(conversation_id=conversation_id)}
        if channel == Channel.email
        else None
    )
    await outbound.send_acknowledgement(
        session,
        conversation_id=conversation_id,
        body=build_body(customer, conversation_id),
        channel=channel,
        settings=settings,
        rules=rules,
        meta=meta,
    )
