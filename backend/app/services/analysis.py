"""Storing AI results and applying routing (ARCHITECTURE §6.2). Torch-free.

The worker runs the classifiers and hands the outcomes to `store_analysis`.
"""

from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.contracts import Prediction
from app.ai.intent_map import IntentMap
from app.enums import AiStatus, AiTask, Direction, JobKind
from app.errors import Conflict, NotFound
from app.models import Conversation, Message, MessageAiResult
from app.services import events, jobs, routing
from app.services.events import EventType

ERROR_MAX_CHARS = 500


@dataclass(frozen=True)
class TaskOutcome:
    task: AiTask
    model_name: str
    model_version: str
    prediction: Prediction | None
    error: str | None
    latency_ms: int | None


async def request_analysis(session: AsyncSession, message_id: int) -> int:
    """POST /messages/{id}/analyze: (re-)queue analysis of an inbound message. Commits."""
    message = await session.get(Message, message_id)
    if message is None:
        raise NotFound(f"Message {message_id} not found.")
    if message.direction != Direction.inbound:
        raise Conflict("Only inbound messages are analysed.", code="not_inbound")
    job_id = await jobs.enqueue(session, JobKind.analyze_message, {"message_id": message_id})
    await session.commit()
    return job_id


async def _upsert(session: AsyncSession, message_id: int, outcome: TaskOutcome) -> None:
    p = outcome.prediction
    error = None if p else (outcome.error or "unknown error")[:ERROR_MAX_CHARS]
    values = {
        "status": AiStatus.ok if p else AiStatus.error,
        "model_name": outcome.model_name,
        "model_version": outcome.model_version,
        "label": p.label if p else None,
        "confidence": p.confidence if p else None,
        "top_k": [s.model_dump() for s in p.top_k] if p else None,
        "error": error,
        "latency_ms": outcome.latency_ms,
    }
    await session.execute(
        insert(MessageAiResult)
        .values(message_id=message_id, task=outcome.task, **values)
        .on_conflict_do_update(constraint="uq_message_ai_results_message_task", set_=values)
    )


async def store_analysis(
    session: AsyncSession,
    message: Message,
    outcomes: list[TaskOutcome],
    *,
    intent_map: IntentMap,
    floor: float,
) -> None:
    """Upsert results, update routing and notify. The caller commits."""
    for outcome in outcomes:
        await _upsert(session, message.id, outcome)
    await session.flush()

    conversation = await session.get_one(
        Conversation, message.conversation_id, with_for_update=True
    )
    intent = next(
        (o.prediction for o in outcomes if o.task == AiTask.intent and o.prediction), None
    )
    reading = routing.IntentReading(intent.label, intent.confidence) if intent else None
    changed = await routing.apply(session, conversation, reading, intent_map, floor)

    await events.emit(
        session,
        EventType.message_analyzed,
        conversation_id=message.conversation_id,
        message_id=message.id,
    )
    if changed:
        await events.emit(
            session, EventType.conversation_updated, conversation_id=message.conversation_id
        )
