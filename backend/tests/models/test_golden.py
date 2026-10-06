"""Golden tests for the real models (ARCHITECTURE §8.5). Run: uv run pytest -m models

Skipped when the weights are absent. Intent (Plan B): the top-1 label must match the
team's notebook, and the confidence must match the repro-v1 export run within ±0.02.
Sentiment: label and confidence within ±0.02 of the team's notebook.
"""

import json

import pytest

from app.ai.text_prep import for_sentiment
from app.config import REPO_ROOT, get_settings

pytestmark = pytest.mark.models

SETTINGS = get_settings()
INTENT_DIR = SETTINGS.resolve_path(SETTINGS.intent_model_dir)
SENTIMENT_DIR = SETTINGS.sentiment_model_dir
TOLERANCE = 0.02

GOLDEN_INTENT = json.loads((INTENT_DIR / "golden_results.json").read_text(encoding="utf-8"))
GOLDEN_SENTIMENT = [
    ("I love the new mobile banking features!", "positive", 0.9893),
    ("I was charged twice and nobody is helping me", "negative", 0.9281),
    ("I need to update my phone number on my account", "neutral", 0.8342),
    ("This is the worst bank I have ever used", "negative", 0.9488),
]

needs_intent = pytest.mark.skipif(
    not (INTENT_DIR / "model.safetensors").exists(), reason="intent weights not present"
)
needs_sentiment = pytest.mark.skipif(
    not (SENTIMENT_DIR / "manifest.json").exists(),
    reason="sentiment model not downloaded (scripts.download_models)",
)


@pytest.fixture(scope="module")
def intent():
    from app.ai.local.intent import LocalIntentClassifier

    return LocalIntentClassifier.load(SETTINGS)


@pytest.fixture(scope="module")
def sentiment():
    from app.ai.local.sentiment import LocalSentimentClassifier

    return LocalSentimentClassifier.load(SETTINGS)


@needs_intent
@pytest.mark.parametrize("case", GOLDEN_INTENT, ids=lambda c: c["expected"])
def test_intent_golden(intent, case):
    [p] = intent.predict([case["text"]])
    assert p.label == case["expected"]
    assert p.confidence == pytest.approx(case["top3"][0][1], abs=TOLERANCE)
    assert [s.label for s in p.top_k] == [label for label, _ in case["top3"]]


@needs_intent
def test_intent_version_is_weights_hash(intent):
    meta = json.loads((INTENT_DIR / "model_meta.json").read_text(encoding="utf-8"))
    assert intent.version == meta["weights_sha256"][:12]


@needs_intent
def test_intent_labels_are_the_mapped_label_set(intent):
    labels = set(json.loads((INTENT_DIR / "id2label.json").read_text(encoding="utf-8")).values())
    preds = intent.predict(["hello", "my card is lost", "transfer failed", "x" * 500, ""])
    assert all(p.label in labels for p in preds)
    assert all(0.0 <= p.confidence <= 1.0 for p in preds)


@needs_intent
def test_intent_batch_equals_single(intent):
    texts = [c["text"] for c in GOLDEN_INTENT] * 3  # 18 > batch size 16
    batch = intent.predict(texts)
    for text, p in zip(texts, batch, strict=True):
        [single] = intent.predict([text])
        assert p.label == single.label
        assert p.confidence == pytest.approx(single.confidence, abs=1e-4)


@needs_sentiment
@pytest.mark.parametrize(("text", "label", "confidence"), GOLDEN_SENTIMENT)
def test_sentiment_golden(sentiment, text, label, confidence):
    [p] = sentiment.predict([for_sentiment(text)])
    assert p.label == label
    assert p.confidence == pytest.approx(confidence, abs=TOLERANCE)
    assert {s.label for s in p.top_k} == {"negative", "neutral", "positive"}


@needs_sentiment
def test_sentiment_version_is_weights_hash(sentiment):
    manifest = json.loads((SENTIMENT_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert sentiment.version == manifest["weights_sha256"][:12]
    assert manifest["revision"] == SETTINGS.sentiment_model_revision


def test_golden_files_present():
    assert (REPO_ROOT / "models/intent/repro-v1/golden_results.json").exists()
