"""Async engine and session factory (asyncpg everywhere, ARCHITECTURE D18)."""

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

SessionMaker = async_sessionmaker[AsyncSession]


def make_engine(url: str, *, null_pool: bool = False) -> AsyncEngine:
    """`null_pool` is for tests, where each test runs on its own event loop."""
    if null_pool:
        return create_async_engine(url, poolclass=NullPool)
    return create_async_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> SessionMaker:
    return async_sessionmaker(engine, expire_on_commit=False)


def asyncpg_dsn(url: str) -> str:
    """SQLAlchemy URL → plain DSN for a raw asyncpg connection (LISTEN)."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
