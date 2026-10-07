"""Job handlers (ARCHITECTURE §12). Each must be idempotent: a lease can expire and the
job runs again. Handlers run inside the job's transaction; the loop commits."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import text_prep
from app.ai.intent_map import IntentMap
from app.ai.llm import LLMClient
from app.channels.registry import AdapterRegistry
from app.compliance.engine import Rule
from app.config import Settings
from app.enums import AiTask, Direction, JobKind
from app.models import Message
from app.services import acknowledgement, analysis, outbound, summaries
from app.services.analysis import TaskOutcome
from app.worker.classifiers import ClassifierProvider

log = logging.getLogger(__name__)


@dataclass
class WorkerContext:
    settings: Settings
    sessionmaker: Any
    classifiers: ClassifierProvider
    registry: AdapterRegistry
    rules: list[Rule]
    llm: LLMClient
    intent_map: IntentMap
    worker_id: str


Handler = Callable[[WorkerContext, AsyncSession, dict[str, Any]], Awaitable[None]]
FailureHook = Callable[[AsyncSession, dict[str, Any], str], Awaitable[None]]


async def _classify(ctx: WorkerContext, task: AiTask, text: str) -> TaskOutcome:
    """Run one classifier off the event loop. Failures become an error outcome so one
    task never blocks the other (§6.2 step 3). latency_ms is inference time only; waiting
    for a model that is still loading is not counted."""
    try:
        classifier = await asyncio.to_thread(ctx.classifiers.get, task)
        started = time.perf_counter()
        [prediction] = await asyncio.to_thread(classifier.predict, [text])
    except Exception as exc:
        name, version = ctx.classifiers.describe(task)
        log.warning("classification failed", extra={"task": str(task), "error": type(exc).__name__})
        return TaskOutcome(task, name, version, None, f"{type(exc).__name__}: {exc}", None)
    latency = int((time.perf_counter() - started) * 1000)
    return TaskOutcome(task, classifier.name, classifier.version, prediction, None, latency)


async def analyze_message(
    ctx: WorkerContext, session: AsyncSession, payload: dict[str, Any]
) -> None:
    message = await session.get(Message, payload["message_id"])
    if message is None or message.direction != Direction.inbound:
        return
    intent = await _classify(
        ctx, AiTask.intent, text_prep.for_intent(message.body, message.channel)
    )
    sentiment = await _classify(
        ctx, AiTask.sentiment, text_prep.for_sentiment(message.body, message.channel)
    )
    await analysis.store_analysis(
        session,
        message,
        [intent, sentiment],
        intent_map=ctx.intent_map,
        floor=ctx.settings.intent_confidence_floor,
    )
    await summaries.maybe_enqueue(
        session,
        message.conversation_id,
        every_n=ctx.settings.summary_every_n_messages,
        llm_configured=ctx.settings.llm_configured,
    )


async def deliver_message(
    ctx: WorkerContext, session: AsyncSession, payload: dict[str, Any]
) -> None:
    await outbound.deliver(session, payload["message_id"], ctx.registry)


async def deliver_message_failed(
    session: AsyncSession, payload: dict[str, Any], error: str
) -> None:
    await outbound.mark_delivery_failed(session, payload["message_id"], error)


async def send_acknowledgement(
    ctx: WorkerContext, session: AsyncSession, payload: dict[str, Any]
) -> None:
    await acknowledgement.acknowledge(
        session, payload["conversation_id"], settings=ctx.settings, rules=ctx.rules
    )


async def summarize_conversation(
    ctx: WorkerContext, session: AsyncSession, payload: dict[str, Any]
) -> None:
    await summaries.summarize(session, payload["conversation_id"], ctx.llm)


async def summarize_conversation_failed(
    session: AsyncSession, payload: dict[str, Any], error: str
) -> None:
    await summaries.notify_failed(session, payload["conversation_id"])


HANDLERS: dict[JobKind, Handler] = {
    JobKind.analyze_message: analyze_message,
    JobKind.deliver_message: deliver_message,
    JobKind.send_acknowledgement: send_acknowledgement,
    JobKind.summarize_conversation: summarize_conversation,
}

ON_PERMANENT_FAILURE: dict[JobKind, FailureHook] = {
    JobKind.deliver_message: deliver_message_failed,
    JobKind.summarize_conversation: summarize_conversation_failed,
}
