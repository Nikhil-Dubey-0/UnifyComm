"""Conversation summaries (ARCHITECTURE §6.5): on demand and every N inbound messages.

The worker job calls the LLM; the API only queues the job. One active job per
conversation is enforced by the uq_jobs_active_summary index.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import LLMClient, SummaryRequest
from app.enums import Direction, JobKind
from app.errors import LLMUnavailable
from app.models import ConversationSummary, Job, Message
from app.services import ai_context, conversations, events, jobs
from app.services.events import EventType

log = logging.getLogger(__name__)

# Bounds the prompt for a first summary of a long conversation.
MAX_MESSAGES_PER_SUMMARY = 50


async def request_summary(
    session: AsyncSession, conversation_id: int, *, llm_configured: bool
) -> int:
    """POST /conversations/{id}/summarize. Commits; returns the (possibly existing) job id."""
    await conversations.get(session, conversation_id)
    if not llm_configured:
        raise LLMUnavailable("AI summaries are not available (no OpenAI API key or disabled).")
    job_id = await jobs.enqueue_summary(session, conversation_id)
    await session.commit()
    return job_id


async def maybe_enqueue(
    session: AsyncSession, conversation_id: int, *, every_n: int, llm_configured: bool
) -> bool:
    """§6.2 step 6: queue a summary once `every_n` inbound messages arrived since the last
    one. The caller commits."""
    if not llm_configured or every_n <= 0:
        return False
    previous = await ai_context.latest_summary(session, conversation_id)
    stmt = (
        select(func.count())
        .select_from(Message)
        .where(Message.conversation_id == conversation_id, Message.direction == Direction.inbound)
    )
    if previous is not None:
        stmt = stmt.where(Message.id > previous.covers_until_message_id)
    if (await session.scalar(stmt) or 0) < every_n:
        return False
    await jobs.enqueue_summary(session, conversation_id)
    return True


async def summarize(session: AsyncSession, conversation_id: int, llm: LLMClient) -> bool:
    """Worker job `summarize_conversation`. Idempotent: skips when nothing new happened
    since the last summary. Raises LLMUnavailable so the job is retried. The caller
    commits. Returns True if a summary was written."""
    previous = await ai_context.latest_summary(session, conversation_id)
    after_id = previous.covers_until_message_id if previous else None
    newest_stmt = select(func.max(Message.id)).where(Message.conversation_id == conversation_id)
    if after_id is not None:
        newest_stmt = newest_stmt.where(Message.id > after_id)
    newest_id = await session.scalar(newest_stmt)
    if newest_id is None:
        return False

    messages = await ai_context.context_messages(
        session, conversation_id, after_id=after_id, limit=MAX_MESSAGES_PER_SUMMARY
    )
    if not messages:
        return False
    previous_payload = (
        {"summary": ai_context.summary_text(previous), **previous.key_points} if previous else None
    )
    output = await llm.summarize(
        SummaryRequest(messages=messages, previous_summary=previous_payload)
    )
    session.add(
        ConversationSummary(
            conversation_id=conversation_id,
            body=output.summary,
            key_points={
                "customer_issue": output.customer_issue,
                "actions_taken": output.actions_taken,
                "open_items": output.open_items,
                "customer_mood": output.customer_mood,
            },
            covers_until_message_id=newest_id,
            model=llm.summary_model,
        )
    )
    await events.emit(session, EventType.summary_updated, conversation_id=conversation_id)
    log.info("summary written", extra={"conversation_id": conversation_id})
    return True


async def notify_failed(session: AsyncSession, conversation_id: int) -> None:
    """The job used all its attempts: tell clients to refetch (the UI shows the failure
    and keeps the last summary, §14)."""
    await events.emit(session, EventType.summary_updated, conversation_id=conversation_id)


async def latest_job(session: AsyncSession, conversation_id: int) -> Job | None:
    return await session.scalar(
        select(Job)
        .where(
            Job.kind == JobKind.summarize_conversation,
            Job.payload["conversation_id"].as_integer() == conversation_id,
        )
        .order_by(Job.id.desc())
        .limit(1)
    )
