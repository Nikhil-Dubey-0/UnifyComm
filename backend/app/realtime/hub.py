"""In-memory WebSocket fan-out (ARCHITECTURE §11). One api process, so one hub."""

import asyncio
import json
import logging
from typing import Any

log = logging.getLogger(__name__)

QUEUE_SIZE = 100


class Subscriber:
    """One browser connection. Its queue is drained by the WebSocket endpoint."""

    def __init__(self, agent_id: int) -> None:
        self.agent_id = agent_id
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.overflowed = asyncio.Event()


class Hub:
    def __init__(self) -> None:
        self._subscribers: set[Subscriber] = set()

    def subscribe(self, agent_id: int) -> Subscriber:
        sub = Subscriber(agent_id)
        self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subscribers.discard(sub)

    def broadcast(self, event: dict[str, Any]) -> None:
        """Non-blocking. A client that falls QUEUE_SIZE events behind is disconnected;
        it reconnects and refetches everything."""
        data = json.dumps(event, separators=(",", ":"))
        for sub in list(self._subscribers):
            try:
                sub.queue.put_nowait(data)
            except asyncio.QueueFull:
                log.warning("dropping slow websocket client", extra={"agent_id": sub.agent_id})
                sub.overflowed.set()
                self.unsubscribe(sub)

    @property
    def size(self) -> int:
        return len(self._subscribers)
