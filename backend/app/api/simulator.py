from fastapi import APIRouter, Response, status

from app.api.deps import CurrentAgent, SessionDep, SettingsDep
from app.channels.simulator import parse_inbound
from app.enums import Channel
from app.schemas.common import ERROR_RESPONSES
from app.schemas.simulator import (
    SimulatorContact,
    SimulatorInboundRequest,
    SimulatorInboundResponse,
    SimulatorThreadMessage,
)
from app.services import ingest, simulator

router = APIRouter(tags=["simulator"], responses=ERROR_RESPONSES)


@router.post(
    "/channels/simulator/inbound",
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": SimulatorInboundResponse, "description": "Duplicate external_id"}},
)
async def simulator_inbound(
    body: SimulatorInboundRequest, session: SessionDep, settings: SettingsDep, response: Response
) -> SimulatorInboundResponse:
    inbound = parse_inbound(
        channel=body.channel,
        sender=body.sender,
        body=body.body,
        sender_name=body.sender_name,
        subject=body.subject,
        external_id=body.external_id,
    )
    result = await ingest.ingest(session, inbound, settings)
    if result.duplicate:
        response.status_code = status.HTTP_200_OK
    return SimulatorInboundResponse(
        message_id=result.message_id,
        conversation_id=result.conversation_id,
        customer_id=result.customer_id,
        duplicate=result.duplicate,
    )


@router.get("/simulator/contacts")
async def simulator_contacts(session: SessionDep, _: CurrentAgent) -> list[SimulatorContact]:
    return await simulator.contacts(session)


@router.get("/simulator/thread")
async def simulator_thread(
    channel: Channel, address: str, session: SessionDep, _: CurrentAgent
) -> list[SimulatorThreadMessage]:
    return await simulator.thread(session, channel, address)
