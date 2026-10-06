"""Integration fixtures: a real PostgreSQL test database (never the dev database)."""

from collections.abc import AsyncIterator

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import Settings
from app.db import SessionMaker, make_engine, make_sessionmaker
from app.main import create_app
from app.models import Agent, Base
from app.services.auth import create_token
from app.worker.handlers import WorkerContext
from app.worker.loop import build_context
from scripts.seed import seed
from tests.integration.helpers import TEST_PASSWORD


@pytest.fixture(scope="session", autouse=True)
def migrated_database(settings: Settings, backend_dir) -> None:
    """Exercise the migration both ways once, then leave the schema at head."""
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))
    cfg.attributes["database_url"] = settings.database_url
    cfg.attributes["skip_logging_config"] = True
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    eng = make_engine(settings.database_url, null_pool=True)
    async with eng.begin() as conn:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield eng
    await eng.dispose()


@pytest.fixture
def sessionmaker(engine: AsyncEngine) -> SessionMaker:
    return make_sessionmaker(engine)


@pytest.fixture
async def db(sessionmaker: SessionMaker) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session


@pytest.fixture
async def app(settings: Settings, engine: AsyncEngine):
    # `engine` first so tables are truncated before the app touches them.
    application = create_app(settings, null_pool=True)
    yield application
    await application.state.engine.dispose()


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def seeded(db: AsyncSession) -> None:
    await seed(db, TEST_PASSWORD)
    await db.commit()


@pytest.fixture
async def agent(db: AsyncSession, seeded) -> Agent:
    from sqlalchemy import select

    return await db.scalar(select(Agent).where(Agent.email == "agent@unifycomm.local"))


@pytest.fixture
def auth_headers(agent: Agent, settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(agent.id, settings)}"}


@pytest.fixture
def worker(settings: Settings, sessionmaker: SessionMaker) -> WorkerContext:
    return build_context(settings, sessionmaker, worker_id="test-worker")
