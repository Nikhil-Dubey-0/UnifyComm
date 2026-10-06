"""Agent authentication: Argon2 passwords (pwdlib) and HS256 JWTs (PyJWT)."""

from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import Unauthorized
from app.models import Agent

ALGORITHM = "HS256"
_hasher = PasswordHash.recommended()
# Verified against when the email is unknown, so timing does not reveal valid emails.
_DUMMY_HASH = _hasher.hash("unifycomm-dummy-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def create_token(agent_id: int, settings: Settings, *, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    claims = {
        "sub": str(agent_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expires_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm=ALGORITHM)


def decode_token(token: str, settings: Settings) -> int:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
        return int(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise Unauthorized("Invalid or expired token.", code="invalid_token") from exc


async def authenticate(session: AsyncSession, email: str, password: str) -> Agent:
    agent = await session.scalar(select(Agent).where(Agent.email == func.lower(email.strip())))
    if agent is None:
        _hasher.verify(password, _DUMMY_HASH)
        raise Unauthorized("Wrong email or password.", code="invalid_credentials")
    if not _hasher.verify(password, agent.password_hash) or not agent.is_active:
        raise Unauthorized("Wrong email or password.", code="invalid_credentials")
    return agent


async def agent_from_token(session: AsyncSession, token: str, settings: Settings) -> Agent:
    agent = await session.get(Agent, decode_token(token, settings))
    if agent is None or not agent.is_active:
        raise Unauthorized("Invalid or expired token.", code="invalid_token")
    return agent
