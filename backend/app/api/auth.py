from fastapi import APIRouter

from app.api.deps import CurrentAgent, SessionDep, SettingsDep
from app.schemas.auth import AgentOut, LoginRequest, TokenResponse
from app.schemas.common import ERROR_RESPONSES
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"], responses=ERROR_RESPONSES)


@router.post("/login")
async def login(body: LoginRequest, session: SessionDep, settings: SettingsDep) -> TokenResponse:
    agent = await auth.authenticate(session, body.email, body.password)
    return TokenResponse(
        access_token=auth.create_token(agent.id, settings), agent=AgentOut.model_validate(agent)
    )


@router.get("/me")
async def me(agent: CurrentAgent) -> AgentOut:
    return AgentOut.model_validate(agent)
