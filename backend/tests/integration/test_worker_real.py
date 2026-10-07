"""The worker in AI_MODE=real against the test database. Run: uv run pytest -m models"""

import json

import pytest
from sqlalchemy import select

from app.models import Conversation, MessageAiResult
from app.worker.loop import build_context
from tests.integration.helpers import AMIT_PHONE, post_inbound, run_all_jobs

pytestmark = pytest.mark.models


@pytest.fixture
def real_worker(settings, sessionmaker):
    real = settings.model_copy(update={"ai_mode": "real"})
    if not (real.resolve_path(real.intent_model_dir) / "model.safetensors").exists():
        pytest.skip("intent weights not present")
    if not (real.sentiment_model_dir / "manifest.json").exists():
        pytest.skip("sentiment model not downloaded (scripts.download_models)")
    ctx = build_context(real, sessionmaker, worker_id="test-real-worker")
    ctx.classifiers.preload()
    return ctx


async def test_real_models_label_and_route(client, db, seeded, real_worker, settings):
    r = (await post_inbound(client, "sms", AMIT_PHONE, "My card was stolen yesterday")).json()
    # analyze_message, send_acknowledgement, deliver_message (the acknowledgement)
    assert await run_all_jobs(real_worker) == 3

    rows = {
        row.task: row
        for row in await db.scalars(
            select(MessageAiResult).where(MessageAiResult.message_id == r["message_id"])
        )
    }
    intent, sentiment = rows["intent"], rows["sentiment"]
    assert (intent.status, intent.label) == ("ok", "lost_or_stolen_card")
    assert intent.model_name == "unifycomm-intent-minilm-l6-213"
    meta = json.loads(
        (settings.resolve_path(settings.intent_model_dir) / "model_meta.json").read_text()
    )
    assert intent.model_version == meta["weights_sha256"][:12]
    assert len(intent.top_k) == 3 and intent.latency_ms is not None
    assert sentiment.status == "ok" and sentiment.label in {"negative", "neutral", "positive"}

    conv = await db.get(Conversation, r["conversation_id"])
    assert (conv.category, conv.priority) == ("fraud_security", "urgent")


async def test_email_history_is_ignored_by_the_models(client, db, seeded, real_worker):
    body = (
        "What's the exchange rate for USD to EUR?\n\n"
        "On Mon, 5 Oct 2026, Support <s@bank.example> wrote:\n"
        "> My card was stolen, I was charged twice, this is the worst bank\n"
    )
    r = (await post_inbound(client, "email", "rahul.sharma@example.com", body)).json()
    await run_all_jobs(real_worker)
    intent = await db.scalar(
        select(MessageAiResult).where(
            MessageAiResult.message_id == r["message_id"], MessageAiResult.task == "intent"
        )
    )
    assert intent.label == "exchange_rate"
