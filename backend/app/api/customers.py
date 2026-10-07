from typing import Annotated

from fastapi import APIRouter, Header, Query, status

from app.api.deps import CurrentAgent, RulesDep, SessionDep, SettingsDep
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.conversations import ComplianceCheckOut, ComplianceOut, MessageOut, SendResponse
from app.schemas.customers import (
    CustomerDetail,
    CustomerOut,
    CustomerWithContacts,
    LinkRequest,
    OutreachRequest,
    PreferenceOut,
    PreferenceUpdate,
)
from app.services import customers, outbound

router = APIRouter(prefix="/customers", tags=["customers"], responses=ERROR_RESPONSES)


@router.get("")
async def list_customers(
    session: SessionDep,
    _: CurrentAgent,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[CustomerWithContacts]:
    return await customers.list_customers(session, q=q, cursor=cursor, limit=limit)


@router.get("/{customer_id}")
async def get_customer(customer_id: int, session: SessionDep, _: CurrentAgent) -> CustomerDetail:
    return await customers.customer_detail(session, customer_id)


@router.post("/{customer_id}/link")
async def link_customer(
    customer_id: int, body: LinkRequest, session: SessionDep, agent: CurrentAgent
) -> CustomerOut:
    target = await customers.link(
        session, target_id=customer_id, source_id=body.source_customer_id, actor=agent
    )
    return CustomerOut.model_validate(target)


@router.put("/{customer_id}/preferences")
async def update_preference(
    customer_id: int, body: PreferenceUpdate, session: SessionDep, agent: CurrentAgent
) -> PreferenceOut:
    pref = await customers.update_preference(
        session,
        customer_id,
        channel=body.channel,
        consent=body.consent,
        dnd=body.dnd,
        actor=agent,
    )
    return PreferenceOut.model_validate(pref)


@router.post("/{customer_id}/outreach", status_code=status.HTTP_201_CREATED)
async def outreach(
    customer_id: int,
    body: OutreachRequest,
    idempotency_key: Annotated[str, Header(min_length=8, max_length=200)],
    session: SessionDep,
    settings: SettingsDep,
    rules: RulesDep,
    agent: CurrentAgent,
) -> SendResponse:
    result = await outbound.send_outreach(
        session,
        customer_id=customer_id,
        agent=agent,
        channel=body.channel,
        body=body.body,
        idempotency_key=idempotency_key,
        settings=settings,
        rules=rules,
    )
    return SendResponse(
        message=MessageOut.model_validate(result.message),
        compliance=ComplianceOut(
            allowed=result.allowed,
            results=[ComplianceCheckOut.model_validate(c) for c in result.checks],
        ),
    )
