"""system_status reads and writes: worker heartbeat, channel health, /health."""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import SystemStatus
from app.schemas.system import HealthOut

log = logging.getLogger(__name__)

HEARTBEAT_KEY = "worker.heartbeat"
CHANNEL_KEY_PREFIX = "channel."


async def put_status(session: AsyncSession, key: str, value: dict[str, Any]) -> None:
    await session.execute(
        insert(SystemStatus)
        .values(key=key, value=value)
        .on_conflict_do_update(
            index_elements=["key"], set_={"value": value, "updated_at": datetime.now(UTC)}
        )
    )


async def health(session: AsyncSession, settings: Settings, providers: list[str]) -> HealthOut:
    try:
        await session.execute(text("SELECT 1"))
        rows = list(await session.scalars(select(SystemStatus)))
    except (SQLAlchemyError, OSError):
        log.warning("health check: database unreachable", exc_info=True)
        return HealthOut(
            db="error",
            worker_heartbeat_at=None,
            ai_mode=settings.ai_mode,
            llm_configured=settings.llm_configured,
            channels={},
        )
    by_key = {r.key: r for r in rows}
    heartbeat = by_key.get(HEARTBEAT_KEY)
    channels = {p: "ok" for p in providers}
    for key, row in by_key.items():
        if key.startswith(CHANNEL_KEY_PREFIX):
            channels[key.removeprefix(CHANNEL_KEY_PREFIX)] = str(row.value.get("status", "unknown"))
    return HealthOut(
        db="ok",
        worker_heartbeat_at=heartbeat.updated_at if heartbeat else None,
        ai_mode=settings.ai_mode,
        llm_configured=settings.llm_configured,
        channels=channels,
    )
