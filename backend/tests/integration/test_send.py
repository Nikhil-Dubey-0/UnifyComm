"""Agent send through the compliance gate (§6.3), delivery and retry (§5.3)."""

import asyncio

import pytest
from sqlalchemy import func, select, text

from app.channels.base import SendResult
from app.compliance.engine import Rule, RuleResult
from app.models import ComplianceCheck, Conversation, Job, Message, ReplyDraft
from app.services import outbound
from tests.integration.helpers import (
    PRIYA_PHONE,
    RAHUL_EMAIL,
    RAHUL_PHONE,
    post_inbound,
    run_all_jobs,
)


@pytest.fixture
async def rahul_conversation(client, worker, seeded) -> int:
    r = await post_inbound(client, "whatsapp", RAHUL_PHONE, "My payment failed")
    await run_all_jobs(worker)
    return r.json()["conversation_id"]


def send(
    client, conversation_id, headers, key, body="We are checking this.", channel="whatsapp", **extra
):
    return client.post(
        f"/api/conversations/{conversation_id}/send",
        json={"channel": channel, "body": body, **extra},
        headers={**headers, "Idempotency-Key": key},
    )


async def test_allowed_send_is_queued_then_delivered(
    client, db, worker, auth_headers, rahul_conversation
):
    r = await send(client, rahul_conversation, auth_headers, "key-allowed-001")
    assert r.status_code == 201
    data = r.json()
    assert data["compliance"] == {"allowed": True, "results": []}
    msg = data["message"]
    assert (msg["direction"], msg["sender_type"], msg["purpose"], msg["delivery_status"]) == (
        "outbound",
        "agent",
        "service_reply",
        "queued",
    )
    assert (msg["provider"], msg["metadata"]["to"]) == ("simulator", "+919876543210")

    conv = await db.get(Conversation, rahul_conversation)
    assert conv.status == "pending"
    assert conv.first_response_at is not None and conv.last_outbound_at is not None

    assert await run_all_jobs(worker) == 1
    delivered = await db.get(Message, msg["id"])
    assert delivered.delivery_status == "delivered"
    assert delivered.external_message_id == f"sim-out-{msg['id']}"

    thread = await client.get(
        "/api/simulator/thread",
        params={"channel": "whatsapp", "address": "+91 98765 43210"},
        headers=auth_headers,
    )
    assert [(m["direction"], m["body"]) for m in thread.json()] == [
        ("inbound", "My payment failed"),
        ("outbound", "We are checking this."),
    ]


async def test_same_idempotency_key_returns_the_stored_result(
    client, db, auth_headers, rahul_conversation
):
    first = await send(client, rahul_conversation, auth_headers, "key-same-0001")
    again = await send(client, rahul_conversation, auth_headers, "key-same-0001", body="changed")
    assert first.status_code == again.status_code == 201
    assert again.json()["message"]["id"] == first.json()["message"]["id"]
    assert again.json()["message"]["body"] == "We are checking this."
    outbound = select(func.count()).select_from(Message).where(Message.direction == "outbound")
    assert await db.scalar(outbound) == 1
    assert (
        await db.scalar(select(func.count()).select_from(Job).where(Job.kind == "deliver_message"))
        == 1
    )


async def test_concurrent_double_click_sends_once(client, db, auth_headers, rahul_conversation):
    results = await asyncio.gather(
        *(send(client, rahul_conversation, auth_headers, "key-double-001") for _ in range(4))
    )
    assert {r.status_code for r in results} == {201}
    assert len({r.json()["message"]["id"] for r in results}) == 1
    outbound = select(func.count()).select_from(Message).where(Message.direction == "outbound")
    assert await db.scalar(outbound) == 1


async def test_key_reused_on_another_conversation_conflicts(
    client, db, auth_headers, rahul_conversation
):
    other = (await post_inbound(client, "sms", PRIYA_PHONE, "card?")).json()["conversation_id"]
    await send(client, rahul_conversation, auth_headers, "key-reused-001")
    r = await send(client, other, auth_headers, "key-reused-001", channel="sms")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "idempotency_key_reused"


async def test_missing_idempotency_key_is_rejected(client, auth_headers, rahul_conversation):
    r = await client.post(
        f"/api/conversations/{rahul_conversation}/send",
        json={"channel": "whatsapp", "body": "hi"},
        headers=auth_headers,
    )
    assert r.status_code == 422


async def test_blocked_send_is_recorded_not_queued(
    client, db, auth_headers, rahul_conversation, monkeypatch
):
    rules = [
        Rule(
            "test.always_fails",
            "fails",
            lambda ctx: RuleResult("test.always_fails", False, "Nope."),
        ),
        Rule("test.always_passes", "passes", lambda ctx: RuleResult("test.always_passes", True)),
    ]
    monkeypatch.setattr("app.api.conversations.RULES", rules)
    r = await send(client, rahul_conversation, auth_headers, "key-blocked-01")
    assert r.status_code == 201
    data = r.json()
    assert data["message"]["delivery_status"] == "blocked"
    assert data["compliance"]["allowed"] is False
    assert [(c["rule_id"], c["passed"], c["reason"]) for c in data["compliance"]["results"]] == [
        ("test.always_fails", False, "Nope."),
        ("test.always_passes", True, None),
    ]

    checks = list(await db.scalars(select(ComplianceCheck).order_by(ComplianceCheck.id)))
    assert len(checks) == 2
    assert checks[0].context["purpose"] == "service_reply"
    assert checks[0].context["consent"] == "opted_in" and "body" not in checks[0].context
    assert (
        await db.scalar(select(func.count()).select_from(Job).where(Job.kind == "deliver_message"))
        == 0
    )
    conv = await db.get(Conversation, rahul_conversation)
    assert conv.status == "open" and conv.first_response_at is None

    detail = (
        await client.get(f"/api/conversations/{rahul_conversation}", headers=auth_headers)
    ).json()
    assert detail["messages"][-1]["compliance_checks"][0]["rule_id"] == "test.always_fails"


async def test_purpose_is_proactive_without_recent_inbound(
    client, db, auth_headers, rahul_conversation
):
    await db.execute(text("UPDATE conversations SET last_inbound_at = now() - interval '25 hours'"))
    await db.commit()
    r = await send(client, rahul_conversation, auth_headers, "key-proactive1")
    assert r.json()["message"]["purpose"] == "proactive"


async def test_email_reply_goes_to_the_customers_email(client, auth_headers, rahul_conversation):
    await post_inbound(client, "email", RAHUL_EMAIL, "Any update?")
    r = await send(client, rahul_conversation, auth_headers, "key-email-0001", channel="email")
    assert r.json()["message"]["metadata"]["to"] == "rahul.sharma@example.com"


async def test_channel_without_inbound_uses_default_provider_and_contact(
    client, auth_headers, rahul_conversation
):
    r = await send(client, rahul_conversation, auth_headers, "key-sms-000001", channel="sms")
    msg = r.json()["message"]
    assert (msg["provider"], msg["metadata"]["to"]) == ("simulator", "+919876543210")


async def test_no_contact_for_channel(client, auth_headers, seeded):
    conv = (await post_inbound(client, "sms", PRIYA_PHONE, "hi")).json()["conversation_id"]
    r = await send(client, conv, auth_headers, "key-nocontact1", channel="email")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "no_contact_for_channel"


async def test_draft_outcome_is_recorded(client, db, agent, auth_headers, rahul_conversation):
    inbound_id = await db.scalar(select(Message.id).where(Message.direction == "inbound"))
    drafts = [
        ReplyDraft(
            conversation_id=rahul_conversation,
            agent_id=agent.id,
            based_on_message_id=inbound_id,
            body=body,
            model="test",
        )
        for body in ("Sorry about that.", "We will check.")
    ]
    db.add_all(drafts)
    await db.commit()

    await send(
        client,
        rahul_conversation,
        auth_headers,
        "key-draft-0001",
        body=" Sorry about that. ",
        draft_id=drafts[0].id,
    )
    await send(
        client,
        rahul_conversation,
        auth_headers,
        "key-draft-0002",
        body="We will check today.",
        draft_id=drafts[1].id,
    )
    for d in drafts:
        await db.refresh(d)
    assert [d.outcome for d in drafts] == ["sent_as_is", "edited"]


async def test_draft_from_another_conversation_is_rejected(
    client, db, agent, auth_headers, rahul_conversation
):
    r = await send(client, rahul_conversation, auth_headers, "key-baddraft1", draft_id=12345)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_draft"


async def test_retry_only_for_failed_deliveries(
    client, db, worker, auth_headers, rahul_conversation
):
    msg_id = (await send(client, rahul_conversation, auth_headers, "key-retry-0001")).json()[
        "message"
    ]["id"]
    r = await client.post(f"/api/messages/{msg_id}/retry", headers=auth_headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_failed"

    await db.execute(
        text("UPDATE messages SET delivery_status = 'failed' WHERE id = :id"), {"id": msg_id}
    )
    await db.execute(text("UPDATE jobs SET status = 'done'"))
    await db.commit()
    r = await client.post(f"/api/messages/{msg_id}/retry", headers=auth_headers)
    assert r.status_code == 202
    await run_all_jobs(worker)
    msg = await db.get(Message, msg_id)
    await db.refresh(msg)
    assert msg.delivery_status == "delivered"


async def test_deliver_is_idempotent(
    client, db, worker, auth_headers, rahul_conversation, monkeypatch
):
    sent = await send(client, rahul_conversation, auth_headers, "key-idem-00001")
    msg_id = sent.json()["message"]["id"]
    await run_all_jobs(worker)

    # A reclaimed lease re-runs deliver_message; the message is no longer queued, so no resend.
    calls = []
    sim = worker.registry.get("simulator")

    async def counting(msg):
        calls.append(msg.message_id)
        return SendResult(ok=True)

    monkeypatch.setattr(sim, "send", counting)
    async with worker.sessionmaker() as session:
        await outbound.deliver(session, msg_id, worker.registry)
        await session.commit()
    assert calls == []


async def test_inbound_cannot_have_delivery_status(db, client):
    await post_inbound(client, "sms", "+91 90000 00021", "hi")
    with pytest.raises(Exception, match="ck_messages_inbound_no_delivery"):
        await db.execute(text("UPDATE messages SET delivery_status = 'sent'"))
