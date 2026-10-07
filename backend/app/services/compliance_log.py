"""Read side of the compliance log page (ARCHITECTURE §10 GET /compliance/checks)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import Unprocessable
from app.models import ComplianceCheck, Conversation, Customer, Message
from app.schemas.common import Page
from app.schemas.compliance import CheckedCustomer, CheckedMessage, ComplianceLogItem


async def list_checks(
    session: AsyncSession,
    *,
    passed: bool | None,
    rule_id: str | None,
    cursor: str | None,
    limit: int,
) -> Page[ComplianceLogItem]:
    """Newest first. The cursor is the last check id of the previous page."""
    stmt = (
        select(ComplianceCheck, Message, Customer)
        .join(Message, Message.id == ComplianceCheck.message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(Customer, Customer.id == Conversation.customer_id)
        .order_by(ComplianceCheck.id.desc())
        .limit(limit + 1)
    )
    if passed is not None:
        stmt = stmt.where(ComplianceCheck.passed.is_(passed))
    if rule_id:
        stmt = stmt.where(ComplianceCheck.rule_id == rule_id)
    if cursor:
        try:
            stmt = stmt.where(ComplianceCheck.id < int(cursor))
        except ValueError as exc:
            raise Unprocessable("Invalid cursor.", code="invalid_cursor") from exc

    rows = (await session.execute(stmt)).all()
    page, more = rows[:limit], len(rows) > limit
    items = [
        ComplianceLogItem(
            id=check.id,
            rule_id=check.rule_id,
            passed=check.passed,
            reason=check.reason,
            context=check.context,
            evaluated_at=check.evaluated_at,
            message=CheckedMessage(
                id=message.id,
                conversation_id=message.conversation_id,
                channel=message.channel,
                purpose=message.purpose,
                sender_type=message.sender_type,
                delivery_status=message.delivery_status,
                is_template=message.is_template,
            ),
            customer=CheckedCustomer(id=customer.id, display_name=customer.display_name),
        )
        for check, message, customer in page
    ]
    return Page[ComplianceLogItem](items=items, next_cursor=str(page[-1][0].id) if more else None)
