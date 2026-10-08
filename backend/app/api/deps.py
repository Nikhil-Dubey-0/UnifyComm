"""Request dependencies: settings, DB session, current agent."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.intent_map import IntentMap, get_intent_map
from app.ai.llm import LLMClient
from app.compliance.engine import Rule
from app.config import Settings
from app.errors import Unauthorized
from app.models import Agent
from app.services import auth

_bearer = HTTPBearer(auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_rules(request: Request) -> list[Rule]:
    return request.app.state.rules


def get_llm(request: Request) -> LLMClient:
    return request.app.state.llm


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request. Services that own the unit of work commit; anything
    left uncommitted is rolled back when the session closes."""
    async with request.app.state.sessionmaker() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
RulesDep = Annotated[list[Rule], Depends(get_rules)]
LLMDep = Annotated[LLMClient, Depends(get_llm)]
IntentMapDep = Annotated[IntentMap, Depends(get_intent_map)]


async def current_agent(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Agent:
    if credentials is None:
        raise Unauthorized("Missing bearer token.", code="not_authenticated")
    return await auth.agent_from_token(session, credentials.credentials, settings)


CurrentAgent = Annotated[Agent, Depends(current_agent)]
