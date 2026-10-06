"""Events: NOTIFY on commit (§6.1 step 8) and the WebSocket bridge (§11)."""

import asyncio
import json

import asyncpg
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.db import asyncpg_dsn
from app.main import create_app
from app.services import events
from app.services.auth import create_token
from app.services.events import EventType
from tests.integration.helpers import RAHUL_PHONE, post_inbound, run_all_jobs


@pytest.fixture
async def listener(settings):
    """Collect uc_events notifications on a separate connection."""
    received: asyncio.Queue[dict] = asyncio.Queue()
    conn = await asyncpg.connect(asyncpg_dsn(settings.database_url))
    await conn.add_listener(events.CHANNEL, lambda *args: received.put_nowait(json.loads(args[-1])))
    yield received
    await conn.close()


async def drain(queue: asyncio.Queue, n: int) -> list[dict]:
    async with asyncio.timeout(3):
        return [await queue.get() for _ in range(n)]


async def test_ingest_and_analysis_notify(client, worker, listener, seeded):
    r = (await post_inbound(client, "whatsapp", RAHUL_PHONE, "My payment failed")).json()
    got = await drain(listener, 2)
    assert [e["type"] for e in got] == ["message.created", "conversation.created"]
    assert got[0]["message_id"] == r["message_id"]
    assert all(e["conversation_id"] == r["conversation_id"] for e in got)

    await run_all_jobs(worker)
    got = await drain(listener, 2)
    assert [e["type"] for e in got] == ["message.analyzed", "conversation.updated"]

    await post_inbound(client, "whatsapp", RAHUL_PHONE, "again")
    assert [e["type"] for e in await drain(listener, 2)] == [
        "message.created",
        "conversation.updated",
    ]


async def test_rolled_back_change_sends_no_event(db, listener):
    await events.emit(db, EventType.conversation_updated, conversation_id=1)
    await db.rollback()
    await events.emit(db, EventType.conversation_updated, conversation_id=2)
    await db.commit()
    [only] = await drain(listener, 1)
    assert only["conversation_id"] == 2
    assert listener.empty()


async def test_duplicate_inbound_sends_no_event(client, listener):
    await post_inbound(client, "sms", "+91 90000 00051", "x", external_id="dup-1")
    await drain(listener, 2)
    await post_inbound(client, "sms", "+91 90000 00051", "x", external_id="dup-1")
    await asyncio.sleep(0.3)
    assert listener.empty()


def test_websocket_receives_events_end_to_end(settings, agent):
    """Real lifespan: EventBridge LISTENs, the hub fans out, the socket delivers."""
    app = create_app(settings, null_pool=True)
    token = create_token(agent.id, settings)
    with TestClient(app) as tc:

        async def bridge_ready() -> None:
            await asyncio.wait_for(app.state.bridge.connected.wait(), 5)

        tc.portal.call(bridge_ready)
        with tc.websocket_connect(f"/ws?token={token}") as ws:
            assert ws.receive_json() == {"type": "hello"}
            r = tc.post(
                "/api/channels/simulator/inbound",
                json={"channel": "whatsapp", "from": RAHUL_PHONE, "body": "hello"},
            )
            assert r.status_code == 201
            first, second = ws.receive_json(), ws.receive_json()
            assert (first["type"], first["message_id"]) == (
                "message.created",
                r.json()["message_id"],
            )
            assert second["type"] == "conversation.created"
            assert set(first) == {"id", "type", "conversation_id", "message_id", "occurred_at"}


def test_websocket_rejects_bad_token(settings, agent):
    app = create_app(settings, null_pool=True)
    with TestClient(app) as tc:
        with pytest.raises(WebSocketDisconnect) as exc:
            with tc.websocket_connect("/ws?token=nope") as ws:
                ws.receive_json()
        assert exc.value.code == 1008
