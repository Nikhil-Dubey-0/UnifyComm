from typing import Annotated

from fastapi import APIRouter, Header, Query, status

from app.api.deps import CurrentAgent, IntentMapDep, SessionDep, SettingsDep
from app.compliance.rules import RULES
from app.enums import ConversationStatus, Priority
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.conversations import (
    ComplianceCheckOut,
    ComplianceOut,
    ConversationDetail,
    ConversationListItem,
    ConversationOut,
    ConversationPatch,
    MessageOut,
    SendRequest,
    SendResponse,
)
from app.services import conversations, inbox, outbound

router = APIRouter(prefix="/conversations", tags=["conversations"], responses=ERROR_RESPONSES)


@router.get("")
async def list_conversations(
    session: SessionDep,
    agent: CurrentAgent,
    status_: Annotated[ConversationStatus | None, Query(alias="status")] = None,
    category: str | None = None,
    priority: Priority | None = None,
    assignee: Annotated[str | None, Query(description="'me', 'unassigned' or an agent id")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[ConversationListItem]:
    filters = inbox.ConversationFilters(
        status=status_, category=category, priority=priority, assignee=assignee, q=q
    )
    return await inbox.list_conversations(
        session, filters, agent_id=agent.id, cursor=cursor, limit=limit
    )


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: int,
    session: SessionDep,
    settings: SettingsDep,
    intent_map: IntentMapDep,
    _: CurrentAgent,
) -> ConversationDetail:
    return await inbox.conversation_detail(
        session,
        conversation_id,
        intent_map=intent_map,
        floor=settings.intent_confidence_floor,
    )


@router.patch("/{conversation_id}")
async def patch_conversation(
    conversation_id: int, body: ConversationPatch, session: SessionDep, agent: CurrentAgent
) -> ConversationOut:
    kwargs = {}
    if "assignee_id" in body.model_fields_set:
        kwargs["assignee_id"] = body.assignee_id
    conversation = await conversations.update_conversation(
        session, conversation_id, actor=agent, status=body.status, **kwargs
    )
    return ConversationOut.model_validate(conversation)


@router.post("/{conversation_id}/send", status_code=status.HTTP_201_CREATED)
async def send(
    conversation_id: int,
    body: SendRequest,
    idempotency_key: Annotated[str, Header(min_length=8, max_length=200)],
    session: SessionDep,
    settings: SettingsDep,
    agent: CurrentAgent,
) -> SendResponse:
    result = await outbound.send_agent_reply(
        session,
        conversation_id=conversation_id,
        agent=agent,
        channel=body.channel,
        body=body.body,
        idempotency_key=idempotency_key,
        draft_id=body.draft_id,
        settings=settings,
        rules=RULES,
    )
    return SendResponse(
        message=MessageOut.model_validate(result.message),
        compliance=ComplianceOut(
            allowed=result.allowed,
            results=[ComplianceCheckOut.model_validate(c) for c in result.checks],
        ),
    )
