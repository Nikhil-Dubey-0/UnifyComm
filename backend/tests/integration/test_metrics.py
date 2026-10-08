"""GET /metrics/summary (ARCHITECTURE §10, §15) over a small known data set."""

from sqlalchemy import select, text

from app.models import Message, ReplyDraft
from tests.integration.helpers import (
    PRIYA_PHONE,
    RAHUL_EMAIL,
    RAHUL_PHONE,
    post_inbound,
    run_all_jobs,
)


async def test_metrics_summary(client, db, worker, agent, auth_headers, seeded):
    rahul = (
        await post_inbound(
            client, "whatsapp", RAHUL_PHONE, "My payment failed but the money was deducted."
        )
    ).json()
    await post_inbound(client, "email", RAHUL_EMAIL, "Any update?")
    priya = (
        await post_inbound(client, "whatsapp", PRIYA_PHONE, "When will my card arrive?")
    ).json()
    await run_all_jobs(worker)

    # Rahul's first response 2 minutes after the conversation started.
    reply = await client.post(
        f"/api/conversations/{rahul['conversation_id']}/send",
        json={"channel": "whatsapp", "body": "We are checking."},
        headers={**auth_headers, "Idempotency-Key": "key-metrics-001"},
    )
    assert reply.json()["compliance"]["allowed"]
    await db.execute(
        text(
            "UPDATE conversations SET first_response_at = created_at + interval '120 seconds' "
            "WHERE id = :id"
        ),
        {"id": rahul["conversation_id"]},
    )
    # Priya opted out of WhatsApp: the reply is blocked (her acknowledgement was too).
    await client.post(
        f"/api/conversations/{priya['conversation_id']}/send",
        json={"channel": "whatsapp", "body": "Soon."},
        headers={**auth_headers, "Idempotency-Key": "key-metrics-002"},
    )
    inbound_id = await db.scalar(select(Message.id).where(Message.direction == "inbound"))
    db.add_all(
        ReplyDraft(
            conversation_id=rahul["conversation_id"],
            agent_id=agent.id,
            based_on_message_id=inbound_id,
            body="x",
            model="m",
            outcome=outcome,
        )
        for outcome in ("sent_as_is", "edited", "edited", "discarded")
    )
    await db.commit()
    await run_all_jobs(worker)

    r = await client.get("/api/metrics/summary", params={"days": 7}, headers=auth_headers)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["days"] == 7 and m["conversations"] == 2
    assert m["inbound_by_channel"] == {"whatsapp": 2, "email": 1}
    # Rahul: acknowledgement + reply delivered; Priya: acknowledgement + reply blocked.
    assert m["outbound_by_status"] == {"delivered": 2, "blocked": 2}
    assert (
        sum(d["inbound"] for d in m["daily"]) == 3 and sum(d["outbound"] for d in m["daily"]) == 4
    )
    assert m["first_response"] == {"count": 1, "median_seconds": 120.0, "p90_seconds": 120.0}
    assert m["drafts"] == {"sent_as_is": 1, "edited": 2, "discarded": 1, "pending": 0}
    assert {c["queue"]: c["count"] for c in m["categories"]} == {
        "Payments & Billing": 1,
        "Cards": 1,
    }
    assert sum(i["count"] for i in m["top_intents"]) == 3
    assert m["needs_review"] == 1  # "Any update?" (fake model: oos)
    assert m["sentiment"]["negative"] == 1 and sum(m["sentiment"].values()) == 3
    assert m["compliance"] == {
        "checked_messages": 4,
        "blocked_messages": 2,
        "blocks_by_rule": [{"rule_id": "consent.opt_out", "count": 2}],
    }
    assert {(x["task"], x["count"]) for x in m["ai_latency"]} == {("intent", 3), ("sentiment", 3)}
    assert all(x["median_ms"] is not None for x in m["ai_latency"])


async def test_metrics_validation_and_auth(client, auth_headers, seeded):
    empty = (await client.get("/api/metrics/summary", headers=auth_headers)).json()
    assert empty["conversations"] == 0 and empty["first_response"]["median_seconds"] is None
    assert (
        await client.get("/api/metrics/summary", params={"days": 0}, headers=auth_headers)
    ).status_code == 422
    assert (
        await client.get("/api/metrics/summary", params={"days": 91}, headers=auth_headers)
    ).status_code == 422
    assert (await client.get("/api/metrics/summary")).status_code == 401
