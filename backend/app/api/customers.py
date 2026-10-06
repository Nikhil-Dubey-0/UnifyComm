from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentAgent, SessionDep
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.customers import CustomerDetail, CustomerOut, CustomerWithContacts, LinkRequest
from app.services import customers

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
