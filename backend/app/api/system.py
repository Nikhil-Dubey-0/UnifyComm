from fastapi import APIRouter, Response, status

from app.api.deps import RegistryDep, SessionDep, SettingsDep
from app.schemas.system import HealthOut
from app.services import system

router = APIRouter(tags=["system"])


@router.get("/health")
async def health(
    session: SessionDep, settings: SettingsDep, registry: RegistryDep, response: Response
) -> HealthOut:
    result = await system.health(session, settings, [str(p) for p in registry.providers()])
    if result.db != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
