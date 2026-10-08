"""system_status reads and writes: worker heartbeat, channel health, /health."""

import logging
from datetime import UTC, datetime, timedelta
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


async def health(session: AsyncSession, settings: Settings) -> HealthOut:
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
    return HealthOut(
        db="ok",
        worker_heartbeat_at=heartbeat.updated_at if heartbeat else None,
        ai_mode=settings.ai_mode,
        llm_configured=settings.llm_configured,
        channels=channel_health(settings, by_key, now=datetime.now(UTC)),
    )


def channel_health(
    settings: Settings, by_key: dict[str, SystemStatus], *, now: datetime
) -> dict[str, str]:
    """§9.2: simulator always ok; gmail from the poller's last report (`stale` when it has
    stopped reporting); twilio from config (webhooks arrive when Twilio sends them)."""
    channels = {"simulator": "ok"}
    if not settings.email_configured:
        channels["gmail"] = "disabled"
    else:
        row = by_key.get(CHANNEL_KEY_PREFIX + "gmail")
        stale_after = timedelta(seconds=max(60, 3 * settings.email_poll_seconds))
        if row is None:
            channels["gmail"] = "starting"
        elif now - row.updated_at > stale_after:
            channels["gmail"] = "stale"
        else:
            channels["gmail"] = str(row.value.get("status", "unknown"))
    if settings.twilio_configured:
        channels["twilio"] = "configured"
    elif settings.twilio_send_configured:
        channels["twilio"] = "no_public_url"
    else:
        channels["twilio"] = "not_configured"
    return channels
