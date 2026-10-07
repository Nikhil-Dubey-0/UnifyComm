"""Compliance with the real §7.6 rules, the acknowledgement template, outreach,
preferences and the compliance log (ARCHITECTURE §6.3, §7.6, §10, §12)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.enums import Channel
from app.models import AuditLog, ComplianceCheck, Conversation, Message
from app.services import acknowledgement, outbound
from tests.integration.helpers import (
    PRIYA_PHONE,
    RAHUL_EMAIL,
    RAHUL_PHONE,
    post_inbound,
    run_all_jobs,
)

IST = ZoneInfo("Asia/Kolkata")


def failed_rules(response_json) -> list[str]:
    return [c["rule_id"] for c in response_json["compliance"]["results"] if not c["passed"]]


def send(client, conversation_id, headers, key, body="We are checking this.", channel="whatsapp"):
    return client.post(
        f"/api/conversations/{conversation_id}/send",
        json={"channel": channel, "body": body},
        headers={**headers, "Idempotency-Key": key},
    )


def outreach(client, customer_id, headers, key, body="Your statement is ready.", channel="sms"):
    return client.post(
        f"/api/customers/{customer_id}/outreach",
        json={"channel": channel, "body": body},
        headers={**headers, "Idempotency-Key": key},
    )


async def messages_of(db, conversation_id) -> list[Message]:
    return list(
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id)
            .execution_options(populate_existing=True)
        )
    )


# --- acknowledgement -------------------------------------------------------------------


async def test_new_conversation_gets_one_delivered_acknowledgement(client, db, worker, seeded):
    r = (await post_inbound(client, "whatsapp", RAHUL_PHONE, "My payment failed")).json()
    await run_all_jobs(worker)
    await post_inbound(client, "whatsapp", RAHUL_PHONE, "Any update?")
    await run_all_jobs(worker)

    msgs = await messages_of(db, r["conversation_id"])
    acks = [m for m in msgs if m.is_template]
    assert len(acks) == 1
    ack = acks[0]
    assert (ack.sender_type, ack.purpose, ack.channel, ack.delivery_status) == (
        "system",
        "service_reply",
        "whatsapp",
        "delivered",
    )
    assert ack.agent_id is None and ack.idempotency_key == f"ack-{r['conversation_id']}"
    assert ack.body.startswith("Hi Rahul, thank you for contacting us.")
    assert f"#{r['conversation_id']}" in ack.body

    conv = await db.get(Conversation, r["conversation_id"])
    await db.refresh(conv)
    # Not an agent response: status and first-response time are unchanged.
    assert conv.status == "open" and conv.first_response_at is None
    assert conv.last_outbound_at is not None


async def test_acknowledgement_job_is_idempotent(db, client, worker, settings, seeded):
    r = (await post_inbound(client, "sms", RAHUL_PHONE, "hello")).json()
    await run_all_jobs(worker)
    for _ in range(2):
        await acknowledgement.acknowledge(
            db, r["conversation_id"], settings=settings, rules=worker.rules
        )
        await db.commit()
    count = select(func.count()).select_from(Message).where(Message.is_template.is_(True))
    assert await db.scalar(count) == 1


async def test_unknown_sender_gets_neutral_greeting_and_email_subject(client, db, worker):
    r = (await post_inbound(client, "email", "someone@example.org", "Hi there")).json()
    await run_all_jobs(worker)
    ack = (await messages_of(db, r["conversation_id"]))[-1]
    assert ack.body.startswith("Hello, thank you for contacting us.")
    assert ack.meta["subject"] == f"We have received your message (#{r['conversation_id']})"
    assert ack.meta["to"] == "someone@example.org"


async def test_acknowledgement_to_opted_out_channel_is_blocked(client, db, worker, seeded):
    r = (await post_inbound(client, "whatsapp", PRIYA_PHONE, "When will my card arrive?")).json()
    await run_all_jobs(worker)
    ack = (await messages_of(db, r["conversation_id"]))[-1]
    assert ack.is_template and ack.delivery_status == "blocked"
    failed = await db.scalars(
        select(ComplianceCheck.rule_id).where(
            ComplianceCheck.message_id == ack.id, ComplianceCheck.passed.is_(False)
        )
    )
    assert list(failed) == ["consent.opt_out"]


# --- agent replies through the real rules ----------------------------------------------


async def test_demo_step_4_reply_to_opted_out_whatsapp_is_blocked(
    client, worker, auth_headers, seeded
):
    r = (await post_inbound(client, "whatsapp", PRIYA_PHONE, "When will my card arrive?")).json()
    await run_all_jobs(worker)
    sent = await send(client, r["conversation_id"], auth_headers, "key-priya-0001")
    assert sent.status_code == 201
    assert sent.json()["message"]["delivery_status"] == "blocked"
    assert failed_rules(sent.json()) == ["consent.opt_out"]
    reason = next(c for c in sent.json()["compliance"]["results"] if not c["passed"])["reason"]
    assert reason == "Customer has opted out of WhatsApp messages."

    # The same reply by SMS (opted in) is a service reply and goes out.
    sms = await send(client, r["conversation_id"], auth_headers, "key-priya-0002", channel="sms")
    assert sms.json()["compliance"]["allowed"] is True


async def test_whatsapp_reply_without_a_whatsapp_inbound_is_blocked(
    client, worker, auth_headers, seeded
):
    r = (await post_inbound(client, "email", RAHUL_EMAIL, "My card is not working")).json()
    await run_all_jobs(worker)
    sent = await send(client, r["conversation_id"], auth_headers, "key-wa-window1")
    assert failed_rules(sent.json()) == ["whatsapp.session_window"]


@pytest.mark.parametrize(
    "body,rule",
    [
        ("Please share the OTP you just received.", "content.sensitive_data"),
        ("Your card 4111 1111 1111 1111 is fine.", "content.sensitive_data"),
        ("This fund has guaranteed returns.", "content.prohibited_claims"),
        ("   ", "content.length"),
    ],
)
async def test_content_rules_block_agent_replies(client, worker, auth_headers, seeded, body, rule):
    r = (await post_inbound(client, "whatsapp", RAHUL_PHONE, "help")).json()
    await run_all_jobs(worker)
    sent = await send(client, r["conversation_id"], auth_headers, f"key-content-{rule}", body=body)
    assert failed_rules(sent.json()) == [rule]


# --- outreach --------------------------------------------------------------------------


async def test_demo_step_5_outreach_to_dnd_customer_is_blocked(client, db, auth_headers, seeded):
    r = await outreach(client, 3, auth_headers, "key-amit-offer1", body="New FD rates: 7.5% p.a.")
    assert r.status_code == 201
    data = r.json()
    assert data["message"]["purpose"] == "proactive"
    assert data["message"]["delivery_status"] == "blocked"
    failed = failed_rules(data)
    assert "dnd.proactive" in failed
    # time.promo_window also fails when the test runs outside 09:00–21:00 IST.
    assert set(failed) <= {"dnd.proactive", "time.promo_window"}

    conv = await db.get(Conversation, data["message"]["conversation_id"])
    assert conv.customer_id == 3 and conv.status == "pending"


async def test_outreach_allowed_inside_the_promo_window(db, agent, settings, worker, seeded):
    noon = datetime(2026, 10, 7, 12, 0, tzinfo=IST)
    result = await outbound.send_outreach(
        db,
        customer_id=1,
        agent=agent,
        channel=Channel.sms,
        body="Your statement is ready.",
        idempotency_key="key-rahul-out-1",
        settings=settings,
        rules=worker.rules,
        now=noon,
    )
    assert result.allowed and result.message.delivery_status == "queued"
    conv = await db.get(Conversation, result.message.conversation_id)
    assert conv.status == "pending" and conv.first_response_at is None

    late = await outbound.send_outreach(
        db,
        customer_id=1,
        agent=agent,
        channel=Channel.sms,
        body="Your statement is ready.",
        idempotency_key="key-rahul-out-2",
        settings=settings,
        rules=worker.rules,
        now=noon.replace(hour=22),
    )
    assert not late.allowed
    assert [c.rule_id for c in late.checks if not c.passed] == ["time.promo_window"]
    # Both attempts joined the same active conversation.
    assert late.message.conversation_id == result.message.conversation_id


async def test_outreach_joins_the_active_conversation(client, worker, auth_headers, seeded):
    r = (await post_inbound(client, "sms", RAHUL_PHONE, "hello")).json()
    await run_all_jobs(worker)
    sent = await outreach(client, 1, auth_headers, "key-join-00001")
    assert sent.json()["message"]["conversation_id"] == r["conversation_id"]


async def test_outreach_idempotency_and_errors(client, auth_headers, seeded):
    first = await outreach(client, 3, auth_headers, "key-out-same-1")
    again = await outreach(client, 3, auth_headers, "key-out-same-1", body="different")
    assert again.status_code == 201
    assert again.json()["message"]["id"] == first.json()["message"]["id"]

    reused = await outreach(client, 1, auth_headers, "key-out-same-1")
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "idempotency_key_reused"

    no_email = await outreach(client, 2, auth_headers, "key-out-noemail", channel="email")
    assert no_email.status_code == 422
    assert no_email.json()["error"]["code"] == "no_contact_for_channel"

    missing = await outreach(client, 999, auth_headers, "key-out-missing")
    assert missing.status_code == 404

    unauth = await client.post(
        "/api/customers/1/outreach",
        json={"channel": "sms", "body": "x"},
        headers={"Idempotency-Key": "key-out-noauth"},
    )
    assert unauth.status_code == 401


# --- preferences -----------------------------------------------------------------------


async def test_update_preference_upserts_and_audits(client, db, agent, auth_headers, seeded):
    r = await client.put(
        "/api/customers/3/preferences",
        json={"channel": "whatsapp", "consent": "opted_in", "dnd": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json() | {"updated_at": None} == {
        "channel": "whatsapp",
        "consent": "opted_in",
        "dnd": True,
        "updated_by": agent.id,
        "updated_at": None,
    }
    r = await client.put(
        "/api/customers/3/preferences",
        json={"channel": "sms", "consent": "opted_out", "dnd": False},
        headers=auth_headers,
    )
    assert r.json()["consent"] == "opted_out"

    audits = list(await db.scalars(select(AuditLog).order_by(AuditLog.id)))
    assert [(a.action, a.target_id, a.actor_agent_id) for a in audits] == [
        ("preferences.update", 3, agent.id),
        ("preferences.update", 3, agent.id),
    ]
    assert audits[0].details == {
        "channel": "whatsapp",
        "before": None,
        "after": {"consent": "opted_in", "dnd": True},
    }
    assert audits[1].details["before"] == {"consent": "opted_in", "dnd": True}

    listed = (await client.get("/api/customers", params={"q": "Amit"}, headers=auth_headers)).json()
    prefs = {p["channel"]: (p["consent"], p["dnd"]) for p in listed["items"][0]["preferences"]}
    assert prefs == {"sms": ("opted_out", False), "whatsapp": ("opted_in", True)}


async def test_preference_validation_and_missing_customer(client, auth_headers, seeded):
    bad = await client.put(
        "/api/customers/1/preferences",
        json={"channel": "whatsapp", "consent": "maybe", "dnd": False},
        headers=auth_headers,
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"
    missing = await client.put(
        "/api/customers/999/preferences",
        json={"channel": "whatsapp", "consent": "opted_in", "dnd": False},
        headers=auth_headers,
    )
    assert missing.status_code == 404


async def test_opt_out_takes_effect_on_the_next_send(client, worker, auth_headers, seeded):
    r = (await post_inbound(client, "whatsapp", RAHUL_PHONE, "help")).json()
    await run_all_jobs(worker)
    await client.put(
        "/api/customers/1/preferences",
        json={"channel": "whatsapp", "consent": "opted_out", "dnd": False},
        headers=auth_headers,
    )
    sent = await send(client, r["conversation_id"], auth_headers, "key-optout-001")
    assert failed_rules(sent.json()) == ["consent.opt_out"]


# --- compliance log --------------------------------------------------------------------


async def test_compliance_log_lists_checks_newest_first_with_filters(
    client, worker, auth_headers, seeded
):
    r = (await post_inbound(client, "whatsapp", PRIYA_PHONE, "card?")).json()
    await run_all_jobs(worker)  # acknowledgement: blocked by consent.opt_out
    await send(client, r["conversation_id"], auth_headers, "key-log-000001")  # blocked again

    blocked = (
        await client.get("/api/compliance/checks", params={"passed": "false"}, headers=auth_headers)
    ).json()
    assert [i["rule_id"] for i in blocked["items"]] == ["consent.opt_out", "consent.opt_out"]
    newest, oldest = blocked["items"]
    assert newest["id"] > oldest["id"]
    assert newest["message"]["sender_type"] == "agent" and oldest["message"]["is_template"]
    assert newest["customer"] == {"id": 2, "display_name": "Priya Verma"}
    assert newest["message"]["delivery_status"] == "blocked"
    assert newest["reason"] == "Customer has opted out of WhatsApp messages."
    assert newest["context"]["consent"] == "opted_out" and "body" not in newest["context"]

    page1 = (
        await client.get("/api/compliance/checks", params={"limit": 10}, headers=auth_headers)
    ).json()
    assert len(page1["items"]) == 10 and page1["next_cursor"]
    page2 = (
        await client.get(
            "/api/compliance/checks",
            params={"limit": 10, "cursor": page1["next_cursor"]},
            headers=auth_headers,
        )
    ).json()
    assert len(page2["items"]) == 6 and page2["next_cursor"] is None
    assert page2["items"][0]["id"] < page1["items"][-1]["id"]

    by_rule = (
        await client.get(
            "/api/compliance/checks", params={"rule_id": "dnd.proactive"}, headers=auth_headers
        )
    ).json()
    assert {i["rule_id"] for i in by_rule["items"]} == {"dnd.proactive"}
    assert len(by_rule["items"]) == 2

    bad = await client.get("/api/compliance/checks", params={"cursor": "abc"}, headers=auth_headers)
    assert bad.status_code == 422
    assert (await client.get("/api/compliance/checks")).status_code == 401
