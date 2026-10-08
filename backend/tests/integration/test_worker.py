"""Worker jobs: analysis + routing (§6.2), queue retries and leases (§5.3, §12)."""

import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update

from app.channels.base import SendResult
from app.enums import AiTask, JobKind
from app.models import Conversation, Job, Message, MessageAiResult, SystemStatus
from app.services import jobs, system
from app.worker.loop import heartbeat, process_one_job
from tests.integration.helpers import (
    AMIT_PHONE,
    RAHUL_EMAIL,
    RAHUL_PHONE,
    post_inbound,
    run_all_jobs,
)


async def conversation(db, conversation_id: int) -> Conversation:
    conv = await db.get(Conversation, conversation_id)
    await db.refresh(conv)
    return conv


async def test_demo_steps_1_and_2_routing(client, db, worker, seeded, auth_headers):
    first = (
        await post_inbound(
            client, "whatsapp", RAHUL_PHONE, "My payment failed but the money was deducted."
        )
    ).json()
    # analyze_message, send_acknowledgement, deliver_message (the acknowledgement)
    assert await run_all_jobs(worker) == 3
    conv = await conversation(db, first["conversation_id"])
    assert (conv.category, conv.primary_intent, conv.priority) == (
        "payments_billing",
        "declined_card_payment",
        "high",
    )

    await post_inbound(client, "email", RAHUL_EMAIL, "Any update?")
    await run_all_jobs(worker)
    conv = await conversation(db, first["conversation_id"])
    assert (conv.category, conv.primary_intent, conv.priority) == (
        "payments_billing",
        "declined_card_payment",
        "high",  # the negative first message is still among the last 3 inbound
    )

    detail = (
        await client.get(f"/api/conversations/{first['conversation_id']}", headers=auth_headers)
    ).json()
    assert detail["conversation"]["category_queue"] == "Payments & Billing"
    first_msg, ack, second_msg = detail["messages"]
    assert (ack["sender_type"], ack["is_template"], ack["delivery_status"]) == (
        "system",
        True,
        "delivered",
    )
    assert first_msg["ai"]["intent"]["category"] == "payments_billing"
    assert first_msg["ai"]["intent"]["needs_review"] is False
    assert first_msg["ai"]["intent"]["model_version"] == "fake-1"
    assert len(first_msg["ai"]["intent"]["top_k"]) == 3
    assert first_msg["ai"]["sentiment"]["label"] == "negative"
    assert second_msg["ai"]["intent"]["label"] == "oos"
    assert second_msg["ai"]["intent"]["needs_review"] is True


async def test_analysis_pending_until_worker_runs(client, auth_headers, seeded):
    r = (await post_inbound(client, "sms", AMIT_PHONE, "hello")).json()
    detail = (
        await client.get(f"/api/conversations/{r['conversation_id']}", headers=auth_headers)
    ).json()
    assert detail["messages"][0]["ai"] == {"intent": None, "sentiment": None}


async def test_fraud_is_urgent(client, db, worker, seeded):
    r = (await post_inbound(client, "sms", AMIT_PHONE, "My card was stolen yesterday")).json()
    await run_all_jobs(worker)
    conv = await conversation(db, r["conversation_id"])
    assert (conv.category, conv.priority) == ("fraud_security", "urgent")


async def test_one_failing_task_does_not_stop_the_other(client, db, worker, monkeypatch):
    real_get = worker.classifiers.get

    def broken_intent(task):
        if task is AiTask.intent:
            raise RuntimeError("weights missing")
        return real_get(task)

    monkeypatch.setattr(worker.classifiers, "get", broken_intent)
    r = (await post_inbound(client, "sms", "+91 90000 00011", "This is terrible")).json()
    await run_all_jobs(worker)

    rows = {
        row.task: row
        for row in await db.scalars(
            select(MessageAiResult).where(MessageAiResult.message_id == r["message_id"])
        )
    }
    assert rows["intent"].status == "error" and "weights missing" in rows["intent"].error
    assert rows["intent"].model_name == "intent-unavailable"
    assert rows["sentiment"].status == "ok" and rows["sentiment"].label == "negative"
    conv = await conversation(db, r["conversation_id"])
    assert conv.category is None and conv.priority == "normal"  # low raised by negative


async def test_reanalysis_upserts(client, db, worker, auth_headers):
    r = (await post_inbound(client, "sms", "+91 90000 00012", "refund please")).json()
    await run_all_jobs(worker)
    resp = await client.post(f"/api/messages/{r['message_id']}/analyze", headers=auth_headers)
    assert resp.status_code == 202
    await run_all_jobs(worker)
    assert await db.scalar(select(func.count()).select_from(MessageAiResult)) == 2


async def test_analyze_rejects_missing_message(client, auth_headers):
    r = await client.post("/api/messages/999/analyze", headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_empty_queue(worker):
    assert await process_one_job(worker) is False


async def test_failed_job_retries_with_backoff_then_fails(
    client, db, worker, monkeypatch, auth_headers
):
    """deliver_message: 3 retryable provider failures → job failed, message failed."""
    sim = worker.registry.get("simulator")

    async def flaky(msg):
        return SendResult(ok=False, error="provider timeout", retryable=True)

    inbound = (await post_inbound(client, "whatsapp", RAHUL_PHONE, "hi")).json()
    await run_all_jobs(worker)  # analysis and the acknowledgement
    monkeypatch.setattr(sim, "send", flaky)
    sent = await client.post(
        f"/api/conversations/{inbound['conversation_id']}/send",
        json={"channel": "whatsapp", "body": "Looking into it"},
        headers={**auth_headers, "Idempotency-Key": "key-flaky-0001"},
    )
    message_id = sent.json()["message"]["id"]
    reply_job = Job.payload["message_id"].as_integer() == message_id

    for attempt in (1, 2):
        before = datetime.now(UTC)
        assert await process_one_job(worker) is True
        job = await db.scalar(
            select(Job)
            .where(Job.kind == "deliver_message", reply_job)
            .execution_options(populate_existing=True)
        )
        assert (job.status, job.attempts) == ("pending", attempt)
        assert job.run_after >= before + timedelta(seconds=5 * 2**attempt - 1)
        assert "provider timeout" in job.last_error
        assert await process_one_job(worker) is False  # not due yet
        await db.execute(update(Job).where(Job.id == job.id).values(run_after=func.now()))
        await db.commit()

    assert await process_one_job(worker) is True
    job = await db.scalar(
        select(Job)
        .where(Job.kind == "deliver_message", reply_job)
        .execution_options(populate_existing=True)
    )
    assert (job.status, job.attempts) == ("failed", 3)
    msg = await db.get(Message, message_id)
    await db.refresh(msg)
    assert msg.delivery_status == "failed" and msg.delivery_error.endswith("provider timeout")


async def test_expired_lease_is_reclaimed(db, worker, client):
    r = (await post_inbound(client, "sms", "+91 90000 00013", "hi")).json()
    await db.execute(
        text(
            "UPDATE jobs SET status = 'running', attempts = 1, locked_by = 'dead-worker', "
            "locked_at = now() - interval '6 minutes'"
        )
    )
    await db.commit()
    assert await process_one_job(worker) is True
    job = await db.scalar(
        select(Job).where(Job.kind == "analyze_message").execution_options(populate_existing=True)
    )
    assert (job.status, job.attempts) == ("done", 2)
    assert (
        await db.scalar(
            select(func.count())
            .select_from(MessageAiResult)
            .where(MessageAiResult.message_id == r["message_id"])
        )
        == 2
    )


async def test_fresh_lease_is_not_stolen(db, worker, client):
    await post_inbound(client, "sms", "+91 90000 00014", "hi")
    await db.execute(
        text("UPDATE jobs SET status = 'running', locked_by = 'other', locked_at = now()")
    )
    await db.commit()
    assert await process_one_job(worker) is False


async def test_lease_expired_after_final_attempt_fails_job(db, worker, client):
    await post_inbound(client, "sms", "+91 90000 00015", "hi")
    await db.execute(
        text(
            "UPDATE jobs SET status = 'running', attempts = 3, "
            "locked_at = now() - interval '6 minutes'"
        )
    )
    await db.commit()
    assert await process_one_job(worker) is True
    job = await db.scalar(
        select(Job).where(Job.kind == "analyze_message").execution_options(populate_existing=True)
    )
    assert job.status == "failed" and "lease expired" in job.last_error


async def test_enqueue_and_claim_order(db, worker):
    a = await jobs.enqueue(db, JobKind.analyze_message, {"message_id": 1})
    b = await jobs.enqueue(db, JobKind.analyze_message, {"message_id": 2})
    await db.commit()
    first = await jobs.claim(db, "w")
    second = await jobs.claim(db, "w")
    assert (first.id, second.id) == (a, b)
    assert (first.status, first.locked_by, first.attempts) == ("running", "w", 1)


async def test_heartbeat_shows_in_health(client, worker):
    assert (await client.get("/api/health")).json()["worker_heartbeat_at"] is None
    await heartbeat(worker)
    health = (await client.get("/api/health")).json()
    assert health["worker_heartbeat_at"] is not None
    assert health["db"] == "ok" and health["ai_mode"] == "fake"
    assert health["llm_configured"] is False
    assert health["channels"] == {
        "simulator": "ok",
        "gmail": "disabled",
        "twilio": "not_configured",
    }


async def test_heartbeat_upserts(db, worker):
    await heartbeat(worker)
    await heartbeat(worker)

    rows = list(await db.scalars(select(SystemStatus)))
    assert [r.key for r in rows] == [system.HEARTBEAT_KEY]
    assert rows[0].value["worker_id"] == "test-worker"


async def test_latency_excludes_waiting_for_the_model_to_load(client, db, worker, monkeypatch):
    """latency_ms is inference time: a job that waited for a slow model load must not
    report the wait (it was showing ~36 s right after a worker restart)."""
    real_get = worker.classifiers.get

    def slow_get(task):
        time.sleep(0.4)  # stands in for the model still loading
        return real_get(task)

    monkeypatch.setattr(worker.classifiers, "get", slow_get)
    r = (await post_inbound(client, "sms", "+91 90000 00061", "refund please")).json()
    await run_all_jobs(worker)
    latencies = await db.scalars(
        select(MessageAiResult.latency_ms).where(MessageAiResult.message_id == r["message_id"])
    )
    assert all(ms is not None and ms < 200 for ms in latencies)
