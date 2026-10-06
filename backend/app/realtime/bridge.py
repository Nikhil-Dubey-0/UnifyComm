"""LISTEN uc_events on a dedicated asyncpg connection and fan out to the hub (§11).

Notifications sent while disconnected are lost, so after every reconnect the bridge
broadcasts {"type": "resync"} and clients refetch.
"""

import asyncio
import contextlib
import json
import logging

import asyncpg

from app.realtime.hub import Hub
from app.services.events import CHANNEL

log = logging.getLogger(__name__)

BACKOFF_START = 1.0
BACKOFF_MAX = 30.0
HEALTH_CHECK_SECONDS = 10.0


class EventBridge:
    def __init__(self, dsn: str, hub: Hub) -> None:
        self._dsn = dsn
        self._hub = hub
        self._task: asyncio.Task | None = None
        self.connected = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="event-bridge")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def _on_notify(self, _conn, _pid, _channel, payload: str) -> None:
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            log.warning("ignoring malformed notification")
            return
        self._hub.broadcast(event)

    async def _run(self) -> None:
        backoff = BACKOFF_START
        first = True
        while True:
            conn: asyncpg.Connection | None = None
            try:
                conn = await asyncpg.connect(self._dsn)
                await conn.add_listener(CHANNEL, self._on_notify)
                self.connected.set()
                log.info("event bridge listening", extra={"channel": CHANNEL})
                if not first:
                    self._hub.broadcast({"type": "resync"})
                first = False
                backoff = BACKOFF_START
                while not conn.is_closed():
                    await asyncio.sleep(HEALTH_CHECK_SECONDS)
                    await conn.execute("SELECT 1")
            except asyncio.CancelledError:
                raise
            except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
                log.warning(
                    "event bridge disconnected; retrying",
                    extra={"error": type(exc).__name__, "retry_in_s": backoff},
                )
            finally:
                self.connected.clear()
                if conn is not None and not conn.is_closed():
                    with contextlib.suppress(Exception):
                        await conn.close(timeout=2)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
