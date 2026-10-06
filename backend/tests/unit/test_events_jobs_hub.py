import json
from datetime import UTC, datetime, timedelta

from app.realtime.hub import QUEUE_SIZE, Hub
from app.services.events import EventType, build_event
from app.services.jobs import retry_delay


def test_event_envelope_shape_and_size():
    event = build_event(
        EventType.message_analyzed,
        conversation_id=104,
        message_id=5512,
        now=datetime(2026, 11, 2, 5, 1, 22, tzinfo=UTC),
    )
    assert event["id"].startswith("evt_") and len(event["id"]) == 10
    assert {k: v for k, v in event.items() if k != "id"} == {
        "type": "message.analyzed",
        "conversation_id": 104,
        "message_id": 5512,
        "occurred_at": "2026-11-02T05:01:22Z",
    }
    assert len(json.dumps(event)) < 1024


def test_event_omits_missing_ids():
    assert "message_id" not in build_event(EventType.conversation_updated, conversation_id=1)


def test_retry_backoff_doubles():
    assert [retry_delay(n) for n in (1, 2, 3)] == [
        timedelta(seconds=10),
        timedelta(seconds=20),
        timedelta(seconds=40),
    ]


async def test_hub_fans_out_and_drops_slow_clients():
    hub = Hub()
    fast, slow = hub.subscribe(1), hub.subscribe(2)
    hub.broadcast({"type": "x"})
    assert json.loads(await fast.queue.get()) == {"type": "x"}

    for _ in range(QUEUE_SIZE):
        hub.broadcast({"type": "y"})
    # `fast` drained one event, so only `slow` overflows.
    assert slow.overflowed.is_set() and not fast.overflowed.is_set()
    assert hub.size == 1
