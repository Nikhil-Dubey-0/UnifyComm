"""Category, sticky primary intent and priority (ARCHITECTURE §7.3–7.5)."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.intent_map import OOS_LABEL, IntentMap
from app.enums import AiStatus, AiTask, Direction, Priority
from app.models import Conversation, Message, MessageAiResult

NEGATIVE_RAISE_CONFIDENCE = 0.70
NEGATIVE_LOOKBACK = 3

_PRIORITY_ORDER = [Priority.low, Priority.normal, Priority.high, Priority.urgent]


@dataclass(frozen=True)
class IntentReading:
    label: str
    confidence: float


@dataclass(frozen=True)
class SentimentReading:
    label: str
    confidence: float


@dataclass(frozen=True)
class RoutingState:
    category: str | None
    primary_intent: str | None
    primary_intent_confidence: float | None
    priority: Priority


def needs_review(intent: IntentReading, floor: float) -> bool:
    """§7.3: `oos` or below the confidence floor."""
    return intent.label == OOS_LABEL or intent.confidence < floor


def is_substantive(intent: IntentReading, intent_map: IntentMap, floor: float) -> bool:
    """§7.4: confident and in a category that may drive routing."""
    if needs_review(intent, floor):
        return False
    category = intent_map.category_of(intent.label)
    return category is not None and category.substantive


def raise_one(priority: Priority) -> Priority:
    index = _PRIORITY_ORDER.index(priority)
    return _PRIORITY_ORDER[min(index + 1, len(_PRIORITY_ORDER) - 1)]


def compute_priority(
    category: str | None, recent_sentiments: list[SentimentReading], intent_map: IntentMap
) -> Priority:
    """§7.5. fraud_security's default is urgent; a recent strong negative raises one level."""
    cat = intent_map.categories.get(category) if category else None
    priority = cat.default_priority if cat else Priority.low
    if priority is Priority.urgent:
        return priority
    if any(
        s.label == "negative" and s.confidence >= NEGATIVE_RAISE_CONFIDENCE
        for s in recent_sentiments[:NEGATIVE_LOOKBACK]
    ):
        priority = raise_one(priority)
    return priority


def decide(
    current: RoutingState,
    intent: IntentReading | None,
    recent_sentiments: list[SentimentReading],
    intent_map: IntentMap,
    floor: float,
) -> RoutingState:
    """Pure routing step for one analysed message. `intent` is None if intent failed."""
    category = current.category
    primary_intent = current.primary_intent
    primary_conf = current.primary_intent_confidence

    if intent is not None and is_substantive(intent, intent_map, floor):
        if category is None or primary_conf is None or intent.confidence > primary_conf:
            category = intent_map.label_to_category[intent.label]
            primary_intent = intent.label
            primary_conf = intent.confidence

    return RoutingState(
        category=category,
        primary_intent=primary_intent,
        primary_intent_confidence=primary_conf,
        priority=compute_priority(category, recent_sentiments, intent_map),
    )


async def apply(
    session: AsyncSession,
    conversation: Conversation,
    intent: IntentReading | None,
    intent_map: IntentMap,
    floor: float,
) -> bool:
    """Update the conversation from its latest analysis. Returns True if anything changed.

    Expects this message's results to be flushed already (they count as "recent").
    """
    recent = await _recent_inbound_sentiments(session, conversation.id)
    current = RoutingState(
        category=conversation.category,
        primary_intent=conversation.primary_intent,
        primary_intent_confidence=conversation.primary_intent_confidence,
        priority=Priority(conversation.priority),
    )
    new = decide(current, intent, recent, intent_map, floor)
    if new == current:
        return False
    conversation.category = new.category
    conversation.primary_intent = new.primary_intent
    conversation.primary_intent_confidence = new.primary_intent_confidence
    conversation.priority = new.priority
    return True


async def _recent_inbound_sentiments(
    session: AsyncSession, conversation_id: int
) -> list[SentimentReading]:
    """Sentiment of the last 3 inbound messages (messages without a result are skipped)."""
    last_inbound = (
        select(Message.id)
        .where(Message.conversation_id == conversation_id, Message.direction == Direction.inbound)
        .order_by(Message.id.desc())
        .limit(NEGATIVE_LOOKBACK)
        .subquery()
    )
    rows = await session.execute(
        select(MessageAiResult.label, MessageAiResult.confidence)
        .join(last_inbound, last_inbound.c.id == MessageAiResult.message_id)
        .where(
            MessageAiResult.task == AiTask.sentiment,
            MessageAiResult.status == AiStatus.ok,
        )
        .order_by(MessageAiResult.message_id.desc())
    )
    return [SentimentReading(label=r.label, confidence=r.confidence) for r in rows]
