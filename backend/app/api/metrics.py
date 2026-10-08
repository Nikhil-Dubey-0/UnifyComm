from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentAgent, IntentMapDep, SessionDep, SettingsDep
from app.schemas.common import ERROR_RESPONSES
from app.schemas.metrics import MetricsSummary
from app.services import metrics

router = APIRouter(prefix="/metrics", tags=["metrics"], responses=ERROR_RESPONSES)


@router.get("/summary")
async def metrics_summary(
    session: SessionDep,
    settings: SettingsDep,
    intent_map: IntentMapDep,
    _: CurrentAgent,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> MetricsSummary:
    return await metrics.summary(
        session,
        days=days,
        intent_map=intent_map,
        floor=settings.intent_confidence_floor,
        timezone=settings.business_timezone,
    )
