"""AI reply drafts (ARCHITECTURE §6.4). Never sent automatically (D13): the agent edits
and sends through services/outbound.py, which records the draft's outcome.
"""

import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import text_prep
from app.ai.intent_map import IntentMap
from app.ai.llm import DraftRequest, LLMClient
from app.enums import AiStatus, AiTask, Channel, Direction, DraftOutcome
from app.errors import Conflict
from app.models import Agent, Customer, Message, MessageAiResult, ReplyDraft
from app.services import ai_context, conversations

log = logging.getLogger(__name__)

CONTEXT_MESSAGES = 12


async def generate(
    session: AsyncSession,
    conversation_id: int,
    *,
    agent: Agent,
    llm: LLMClient,
    intent_map: IntentMap,
    channel: Channel | None = None,
    instructions: str | None = None,
) -> ReplyDraft:
    """Build the redacted context, call the LLM (no transaction held during the call),
    store the draft and mark earlier pending drafts of the conversation as discarded.
    Raises LLMUnavailable (503). Commits."""
    conversation = await conversations.get(session, conversation_id)
    latest_inbound = await session.scalar(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.direction == Direction.inbound)
        .order_by(Message.id.desc())
        .limit(1)
    )
    if latest_inbound is None:
        raise Conflict("There is no customer message to reply to yet.", code="no_customer_message")
    customer = await session.get_one(Customer, conversation.customer_id)
    summary = await ai_context.latest_summary(session, conversation_id)
    messages = await ai_context.context_messages(session, conversation_id, limit=CONTEXT_MESSAGES)
    sentiment = await session.scalar(
        select(MessageAiResult.label).where(
            MessageAiResult.message_id == latest_inbound.id,
            MessageAiResult.task == AiTask.sentiment,
            MessageAiResult.status == AiStatus.ok,
        )
    )
    category = intent_map.categories.get(conversation.category) if conversation.category else None
    request = DraftRequest(
        reply_channel=str(channel or latest_inbound.channel),
        messages=messages,
        customer_first_name=_first_name(customer),
        agent_name=agent.name,
        category=category.queue if category else None,
        intent=conversation.primary_intent,
        sentiment=sentiment,
        previous_summary=ai_context.summary_text(summary) if summary else None,
        instructions=text_prep.redact_pii(instructions) if instructions else None,
    )
    based_on_id, agent_id = latest_inbound.id, agent.id
    # Release the connection while waiting up to OPENAI_TIMEOUT_SECONDS for the LLM.
    # (rollback expires loaded objects: use only the plain values captured above.)
    await session.rollback()

    output = await llm.draft(request)

    await session.execute(
        update(ReplyDraft)
        .where(
            ReplyDraft.conversation_id == conversation_id,
            ReplyDraft.outcome == DraftOutcome.pending,
        )
        .values(outcome=DraftOutcome.discarded)
    )
    draft = ReplyDraft(
        conversation_id=conversation_id,
        agent_id=agent_id,
        based_on_message_id=based_on_id,
        body=output.reply.strip(),
        verify_hints=[h.strip() for h in output.verify_hints if h.strip()],
        model=llm.draft_model,
    )
    session.add(draft)
    await session.commit()
    await session.refresh(draft)
    log.info("draft generated", extra={"conversation_id": conversation_id, "draft_id": draft.id})
    return draft


def _first_name(customer: Customer) -> str | None:
    """Only verified customers are greeted by name; an unknown sender's display name may
    be a phone number or a provider profile name."""
    if not customer.verified or not customer.display_name.strip():
        return None
    return customer.display_name.split()[0]
