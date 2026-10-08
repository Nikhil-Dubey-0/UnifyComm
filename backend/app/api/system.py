from fastapi import APIRouter, Response, status

from app.api.deps import SessionDep, SettingsDep
from app.schemas.system import HealthOut
from app.services import system

router = APIRouter(tags=["system"])


@router.get("/health")
async def health(session: SessionDep, settings: SettingsDep, response: Response) -> HealthOut:
    result = await system.health(session, settings)
    if result.db != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
