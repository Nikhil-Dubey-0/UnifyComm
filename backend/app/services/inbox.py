"""Read side of the agent workspace: conversation list and detail (ARCHITECTURE §10)."""

import base64
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    Select,
    case,
    cast,
    exists,
    func,
    literal,
    literal_column,
    or_,
    select,
    tuple_,
)
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.intent_map import IntentMap
from app.enums import AiTask, ConversationStatus, Priority
from app.errors import NotFound, Unprocessable
from app.models import (
    ComplianceCheck,
    Conversation,
    ConversationSummary,
    Customer,
    CustomerContact,
    Message,
    MessageAiResult,
)
from app.schemas.common import Page
from app.schemas.conversations import (
    AiResultOut,
    ComplianceCheckOut,
    ConversationDetail,
    ConversationListItem,
    ConversationOut,
    CustomerRef,
    CustomerWithContactsRef,
    MessageAi,
    MessagePreview,
    MessageWithAnalysis,
    SummaryOut,
)
from app.services.routing import IntentReading, needs_review

PREVIEW_CHARS = 140
_PRIORITY_RANK = {Priority.urgent: 0, Priority.high: 1, Priority.normal: 2, Priority.low: 3}
_INFINITY = "infinity"


@dataclass(frozen=True)
class ConversationFilters:
    status: ConversationStatus | None = None
    category: str | None = None
    priority: Priority | None = None
    assignee: str | None = None  # "me", "unassigned" or an agent id
    q: str | None = None


def _priority_rank():
    return case(_PRIORITY_RANK, value=Conversation.priority, else_=len(_PRIORITY_RANK))


def _waiting_since():
    # Conversations without inbound messages sort after those waiting for a reply.
    return func.coalesce(Conversation.last_inbound_at, literal_column("'infinity'::timestamptz"))


def _encode_cursor(rank: int, waiting: datetime | str, conv_id: int) -> str:
    waiting_s = waiting if isinstance(waiting, str) else waiting.isoformat()
    raw = json.dumps([rank, waiting_s, conv_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, str, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        rank, waiting, conv_id = json.loads(base64.urlsafe_b64decode(padded))
        return int(rank), str(waiting), int(conv_id)
    except (ValueError, TypeError) as exc:
        raise Unprocessable("Invalid cursor.", code="invalid_cursor") from exc


def _apply_filters(stmt: Select, filters: ConversationFilters, agent_id: int) -> Select:
    if filters.status:
        stmt = stmt.where(Conversation.status == filters.status)
    if filters.category:
        stmt = stmt.where(Conversation.category == filters.category)
    if filters.priority:
        stmt = stmt.where(Conversation.priority == filters.priority)
    if filters.assignee == "me":
        stmt = stmt.where(Conversation.assignee_id == agent_id)
    elif filters.assignee == "unassigned":
        stmt = stmt.where(Conversation.assignee_id.is_(None))
    elif filters.assignee:
        try:
            stmt = stmt.where(Conversation.assignee_id == int(filters.assignee))
        except ValueError as exc:
            raise Unprocessable(
                "assignee must be 'me', 'unassigned' or an agent id.", code="invalid_assignee"
            ) from exc
    if filters.q:
        pattern = (
            "%" + filters.q.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
        )
        stmt = stmt.where(
            or_(
                Customer.display_name.ilike(pattern),
                exists().where(
                    CustomerContact.customer_id == Customer.id,
                    CustomerContact.value_normalized.ilike(pattern),
                ),
            )
        )
    return stmt


async def list_conversations(
    session: AsyncSession,
    filters: ConversationFilters,
    *,
    agent_id: int,
    cursor: str | None,
    limit: int,
) -> Page[ConversationListItem]:
    """Inbox order (§7.5): priority, then longest-waiting first, then id."""
    rank = _priority_rank().label("rank")
    waiting = _waiting_since().label("waiting")
    stmt = (
        select(Conversation, Customer, rank, waiting)
        .join(Customer, Customer.id == Conversation.customer_id)
        .order_by(rank, waiting, Conversation.id)
        .limit(limit + 1)
    )
    stmt = _apply_filters(stmt, filters, agent_id)
    if cursor:
        c_rank, c_waiting, c_id = _decode_cursor(cursor)
        stmt = stmt.where(
            tuple_(_priority_rank(), _waiting_since(), Conversation.id)
            > tuple_(
                literal(c_rank), cast(literal(c_waiting), TIMESTAMP(timezone=True)), literal(c_id)
            )
        )

    rows = (await session.execute(stmt)).all()
    page, more = rows[:limit], len(rows) > limit
    previews = await _last_messages(session, [r.Conversation.id for r in page])

    items = [
        ConversationListItem.model_validate(
            {
                **ConversationOut.model_validate(r.Conversation).model_dump(
                    exclude={"category_queue"}
                ),
                "customer": CustomerRef.model_validate(r.Customer),
                "last_message": previews.get(r.Conversation.id),
            }
        )
        for r in page
    ]
    next_cursor = None
    if more:
        last = page[-1]
        waiting_value = _INFINITY if last.Conversation.last_inbound_at is None else last.waiting
        next_cursor = _encode_cursor(last.rank, waiting_value, last.Conversation.id)
    return Page[ConversationListItem](items=items, next_cursor=next_cursor)


async def _last_messages(
    session: AsyncSession, conversation_ids: list[int]
) -> dict[int, MessagePreview]:
    if not conversation_ids:
        return {}
    rows = await session.scalars(
        select(Message)
        .where(Message.conversation_id.in_(conversation_ids))
        .ext(distinct_on(Message.conversation_id))
        .order_by(Message.conversation_id, Message.id.desc())
    )
    return {
        m.conversation_id: MessagePreview(
            id=m.id,
            channel=m.channel,
            direction=m.direction,
            sender_type=m.sender_type,
            body_preview=m.body[:PREVIEW_CHARS],
            created_at=m.created_at,
        )
        for m in rows
    }


def ai_result_out(result: MessageAiResult, intent_map: IntentMap, floor: float) -> AiResultOut:
    out = AiResultOut(
        task=result.task,
        status=result.status,
        label=result.label,
        confidence=result.confidence,
        top_k=result.top_k,
        model_name=result.model_name,
        model_version=result.model_version,
        error=result.error,
        latency_ms=result.latency_ms,
        created_at=result.created_at,
    )
    if result.task == AiTask.intent and result.label is not None and result.confidence is not None:
        category = intent_map.category_of(result.label)
        out.category = category.key if category else None
        out.category_queue = category.queue if category else None
        out.needs_review = needs_review(IntentReading(result.label, result.confidence), floor)
    return out


async def conversation_detail(
    session: AsyncSession, conversation_id: int, *, intent_map: IntentMap, floor: float
) -> ConversationDetail:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise NotFound(f"Conversation {conversation_id} not found.")
    customer = await session.get_one(Customer, conversation.customer_id)
    contacts = list(
        await session.scalars(
            select(CustomerContact)
            .where(CustomerContact.customer_id == customer.id)
            .order_by(CustomerContact.id)
        )
    )
    messages = list(
        await session.scalars(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)
        )
    )
    ids = [m.id for m in messages]

    ai: dict[int, MessageAi] = defaultdict(MessageAi)
    checks: dict[int, list[ComplianceCheckOut]] = defaultdict(list)
    if ids:
        for r in await session.scalars(
            select(MessageAiResult).where(MessageAiResult.message_id.in_(ids))
        ):
            setattr(ai[r.message_id], r.task, ai_result_out(r, intent_map, floor))
        for c in await session.scalars(
            select(ComplianceCheck)
            .where(ComplianceCheck.message_id.in_(ids))
            .order_by(ComplianceCheck.id)
        ):
            checks[c.message_id].append(ComplianceCheckOut.model_validate(c))

    summary = await session.scalar(
        select(ConversationSummary)
        .where(ConversationSummary.conversation_id == conversation_id)
        .order_by(ConversationSummary.id.desc())
        .limit(1)
    )
    return ConversationDetail(
        conversation=ConversationOut.model_validate(conversation),
        customer=CustomerWithContactsRef(
            id=customer.id,
            display_name=customer.display_name,
            verified=customer.verified,
            contacts=contacts,  # type: ignore[arg-type]
        ),
        messages=[
            MessageWithAnalysis.model_validate(m).model_copy(
                update={"ai": ai[m.id], "compliance_checks": checks[m.id]}
            )
            for m in messages
        ],
        latest_summary=SummaryOut.model_validate(summary) if summary else None,
    )
