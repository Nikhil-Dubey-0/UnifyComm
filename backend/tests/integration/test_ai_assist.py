"""Drafts (§6.4) and summaries (§6.5) with a fake LLM; LLM-unavailable behaviour (§14)."""

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text, update

from app.errors import LLMUnavailable
from app.models import ConversationSummary, Job, ReplyDraft
from app.worker.loop import process_one_job
from tests.integration.helpers import (
    PRIYA_PHONE,
    RAHUL_PHONE,
    FakeLLM,
    post_inbound,
    run_all_jobs,
)

LLM_ON = {"llm_enabled": True, "openai_api_key": SecretStr("sk-test-not-used")}


@pytest.fixture
def llm(app, worker) -> FakeLLM:
    fake = FakeLLM()
    app.state.llm = fake
    app.state.settings = app.state.settings.model_copy(update=LLM_ON)
    worker.llm = fake
    worker.settings = worker.settings.model_copy(update=LLM_ON)
    return fake


@pytest.fixture
async def rahul(client, worker, seeded) -> int:
    r = await post_inbound(
        client,
        "whatsapp",
        RAHUL_PHONE,
        "My payment failed but the money was deducted. Card 4111 1111 1111 1111, "
        "call me on +91 98765 43210.",
    )
    await run_all_jobs(worker)
    return r.json()["conversation_id"]


def draft(client, conversation_id, headers, **body):
    return client.post(
        f"/api/conversations/{conversation_id}/drafts", json=body or None, headers=headers
    )


# --- drafts ----------------------------------------------------------------------------


async def test_draft_without_llm_returns_503_and_stores_nothing(client, db, auth_headers, rahul):
    r = await draft(client, rahul, auth_headers)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "llm_unavailable"
    assert r.json()["error"]["message"].startswith("AI assistance is")
    assert await db.scalar(select(func.count()).select_from(ReplyDraft)) == 0


async def test_draft_is_stored_with_redacted_context(client, db, agent, auth_headers, llm, rahul):
    # A blocked reply must not reach the model.
    await client.post(
        f"/api/conversations/{rahul}/send",
        json={"channel": "whatsapp", "body": "Please share your OTP."},
        headers={**auth_headers, "Idempotency-Key": "key-blocked-ctx1"},
    )
    r = await draft(client, rahul, auth_headers, instructions="Mention card 4111111111111111")
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["body"] == "Draft reply #1"
    assert data["verify_hints"] == ["Check the transaction status"]
    assert (data["model"], data["outcome"], data["conversation_id"]) == (
        "fake-llm-draft",
        "pending",
        rahul,
    )

    [request] = llm.draft_requests
    assert request.reply_channel == "whatsapp"
    assert (request.customer_first_name, request.agent_name) == ("Rahul", agent.name)
    assert request.category == "Payments & Billing"
    assert request.sentiment == "negative"
    assert request.instructions == "Mention card [CARD]"
    # Only the customer's message: the acknowledgement and the blocked reply are left out.
    [only] = request.messages
    assert only.author == "customer"
    assert "[CARD]" in only.body and "[PHONE]" in only.body
    assert "4111" not in only.body and "98765" not in only.body

    stored = await db.get(ReplyDraft, data["id"])
    assert stored.agent_id == agent.id and stored.based_on_message_id == data["based_on_message_id"]


async def test_regenerate_discards_the_previous_pending_draft(client, db, auth_headers, llm, rahul):
    first = (await draft(client, rahul, auth_headers)).json()
    second = (await draft(client, rahul, auth_headers, channel="email")).json()
    assert llm.draft_requests[1].reply_channel == "email"
    outcomes = dict(
        (await db.execute(select(ReplyDraft.id, ReplyDraft.outcome).order_by(ReplyDraft.id))).all()
    )
    assert outcomes == {first["id"]: "discarded", second["id"]: "pending"}


async def test_sending_a_draft_records_its_outcome(client, db, auth_headers, llm, rahul):
    d = (await draft(client, rahul, auth_headers)).json()
    r = await client.post(
        f"/api/conversations/{rahul}/send",
        json={
            "channel": "whatsapp",
            "body": d["body"] + " We will update you today.",
            "draft_id": d["id"],
        },
        headers={**auth_headers, "Idempotency-Key": "key-draft-out-01"},
    )
    assert r.json()["compliance"]["allowed"] is True
    assert r.json()["message"]["draft_id"] == d["id"]
    stored = await db.get(ReplyDraft, d["id"])
    await db.refresh(stored)
    assert stored.outcome == "edited"


async def test_manual_send_discards_pending_drafts(client, db, auth_headers, llm, rahul):
    d = (await draft(client, rahul, auth_headers)).json()
    await client.post(
        f"/api/conversations/{rahul}/send",
        json={"channel": "whatsapp", "body": "Typed by hand."},
        headers={**auth_headers, "Idempotency-Key": "key-manual-0001"},
    )
    stored = await db.get(ReplyDraft, d["id"])
    await db.refresh(stored)
    assert stored.outcome == "discarded"


async def test_llm_failure_returns_503(client, db, auth_headers, llm, rahul):
    llm.error = LLMUnavailable("The AI assistant is unavailable right now.")
    r = await draft(client, rahul, auth_headers)
    assert r.status_code == 503 and r.json()["error"]["code"] == "llm_unavailable"
    assert await db.scalar(select(func.count()).select_from(ReplyDraft)) == 0


async def test_draft_needs_a_customer_message(client, auth_headers, llm, seeded):
    out = await client.post(
        "/api/customers/3/outreach",
        json={"channel": "sms", "body": "Hello"},
        headers={**auth_headers, "Idempotency-Key": "key-out-nodraft"},
    )
    r = await draft(client, out.json()["message"]["conversation_id"], auth_headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_customer_message"


async def test_draft_errors(client, auth_headers, llm, rahul):
    assert (await draft(client, 999, auth_headers)).status_code == 404
    long = await draft(client, rahul, auth_headers, instructions="x" * 1_001)
    assert long.status_code == 422
    assert (await client.post(f"/api/conversations/{rahul}/drafts")).status_code == 401


# --- summaries -------------------------------------------------------------------------


def summarize(client, conversation_id, headers):
    return client.post(f"/api/conversations/{conversation_id}/summarize", headers=headers)


async def test_summarize_without_llm_returns_503(client, auth_headers, rahul):
    r = await summarize(client, rahul, auth_headers)
    assert r.status_code == 503 and r.json()["error"]["code"] == "llm_unavailable"


async def test_summarize_on_demand(client, db, worker, auth_headers, llm, rahul):
    r = await summarize(client, rahul, auth_headers)
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    # A second click while the job is queued returns the same job.
    assert (await summarize(client, rahul, auth_headers)).json()["job_id"] == job_id

    detail = (await client.get(f"/api/conversations/{rahul}", headers=auth_headers)).json()
    assert detail["summary_job"]["status"] == "pending" and detail["latest_summary"] is None

    await run_all_jobs(worker)
    detail = (await client.get(f"/api/conversations/{rahul}", headers=auth_headers)).json()
    summary = detail["latest_summary"]
    assert summary["body"] == "Summary #1"
    assert summary["key_points"] == {
        "customer_issue": "Payment failed but money was deducted.",
        "actions_taken": [],
        "open_items": ["Check the deduction"],
        "customer_mood": "frustrated",
    }
    # Covers everything so far, including the acknowledgement.
    assert summary["covers_until_message_id"] == detail["messages"][-1]["id"]
    assert summary["model"] == "fake-llm-summary"
    assert detail["summary_job"] == {**detail["summary_job"], "job_id": job_id, "status": "done"}
    [request] = llm.summary_requests
    assert request.previous_summary is None
    assert "[CARD]" in request.messages[0].body

    # Nothing new: the job runs but writes no second summary.
    await summarize(client, rahul, auth_headers)
    await run_all_jobs(worker)
    assert await db.scalar(select(func.count()).select_from(ConversationSummary)) == 1

    # New message: incremental summary with the previous one as input.
    await post_inbound(client, "whatsapp", RAHUL_PHONE, "Any update?")
    await run_all_jobs(worker)
    await summarize(client, rahul, auth_headers)
    await run_all_jobs(worker)
    second = llm.summary_requests[-1]
    assert second.previous_summary["customer_issue"] == "Payment failed but money was deducted."
    assert [m.body for m in second.messages] == ["Any update?"]


async def test_summary_every_n_inbound_messages(client, db, worker, llm, seeded):
    worker.settings = worker.settings.model_copy(update={"summary_every_n_messages": 2})
    r = (await post_inbound(client, "sms", PRIYA_PHONE, "When will my card arrive?")).json()
    await run_all_jobs(worker)
    assert await db.scalar(select(func.count()).select_from(ConversationSummary)) == 0
    await post_inbound(client, "sms", PRIYA_PHONE, "It has been ten days.")
    await run_all_jobs(worker)
    summaries = list(await db.scalars(select(ConversationSummary)))
    assert [s.conversation_id for s in summaries] == [r["conversation_id"]]


async def test_no_threshold_summary_without_llm(client, db, worker, seeded):
    worker.settings = worker.settings.model_copy(update={"summary_every_n_messages": 1})
    await post_inbound(client, "sms", PRIYA_PHONE, "hello")
    await run_all_jobs(worker)
    jobs = select(func.count()).select_from(Job).where(Job.kind == "summarize_conversation")
    assert await db.scalar(jobs) == 0


async def test_failed_summary_job_keeps_the_last_summary(
    client, db, worker, auth_headers, llm, rahul
):
    await summarize(client, rahul, auth_headers)
    await run_all_jobs(worker)
    await post_inbound(client, "whatsapp", RAHUL_PHONE, "Hello?")
    await run_all_jobs(worker)

    llm.error = LLMUnavailable("down")
    await summarize(client, rahul, auth_headers)
    for _ in range(3):
        await db.execute(
            update(Job)
            .where(Job.kind == "summarize_conversation", Job.status == "pending")
            .values(run_after=text("now()"))
        )
        await db.commit()
        assert await process_one_job(worker) is True

    detail = (await client.get(f"/api/conversations/{rahul}", headers=auth_headers)).json()
    assert detail["summary_job"]["status"] == "failed"
    assert detail["latest_summary"]["body"] == "Summary #1"
    # A failed job no longer blocks a new request.
    llm.error = None
    assert (await summarize(client, rahul, auth_headers)).status_code == 202
    await run_all_jobs(worker)
    detail = (await client.get(f"/api/conversations/{rahul}", headers=auth_headers)).json()
    assert detail["latest_summary"]["body"] == "Summary #5"


async def test_summarize_unknown_conversation(client, auth_headers, llm):
    assert (await summarize(client, 999, auth_headers)).status_code == 404
