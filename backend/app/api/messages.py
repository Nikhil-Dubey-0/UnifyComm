from fastapi import APIRouter, status

from app.api.deps import CurrentAgent, SessionDep
from app.schemas.common import ERROR_RESPONSES, JobAccepted
from app.services import analysis, outbound

router = APIRouter(prefix="/messages", tags=["messages"], responses=ERROR_RESPONSES)


@router.post("/{message_id}/analyze", status_code=status.HTTP_202_ACCEPTED)
async def analyze(message_id: int, session: SessionDep, _: CurrentAgent) -> JobAccepted:
    return JobAccepted(job_id=await analysis.request_analysis(session, message_id))


@router.post("/{message_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry(message_id: int, session: SessionDep, _: CurrentAgent) -> JobAccepted:
    return JobAccepted(job_id=await outbound.retry_delivery(session, message_id))
