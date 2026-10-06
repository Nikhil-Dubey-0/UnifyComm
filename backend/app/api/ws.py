"""GET /ws?token=<JWT> (ARCHITECTURE §11). Events are invalidation hints only."""

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.errors import Unauthorized
from app.realtime.hub import Hub
from app.services import auth

router = APIRouter()

PING_SECONDS = 25.0


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = "") -> None:
    app = websocket.app
    try:
        async with app.state.sessionmaker() as session:
            agent = await auth.agent_from_token(session, token, app.state.settings)
    except Unauthorized:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    hub: Hub = app.state.hub
    await websocket.accept()
    sub = hub.subscribe(agent.id)
    # The client sends nothing; reading detects disconnects promptly.
    reader = asyncio.create_task(_drain_client(websocket))
    try:
        await websocket.send_json({"type": "hello"})
        while not reader.done() and not sub.overflowed.is_set():
            try:
                data = await asyncio.wait_for(sub.queue.get(), timeout=PING_SECONDS)
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue
            await websocket.send_text(data)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(sub)
        reader.cancel()
        with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
            await reader
        if sub.overflowed.is_set():
            with contextlib.suppress(RuntimeError):
                await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)


async def _drain_client(websocket: WebSocket) -> None:
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            await websocket.receive_text()
