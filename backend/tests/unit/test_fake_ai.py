import json

import pytest

from app.ai.fake import INTENT_RULES, FakeIntentClassifier, FakeSentimentClassifier
from app.ai.text_prep import for_intent, for_sentiment
from app.config import REPO_ROOT

INTENT_LABELS = set(
    json.loads((REPO_ROOT / "models/intent/repro-v1/id2label.json").read_text()).values()
)
SENTIMENT_LABELS = {"negative", "neutral", "positive"}


def test_fake_intent_labels_come_from_the_real_label_set():
    assert {label for _, label in INTENT_RULES} <= INTENT_LABELS
    for text in ["My card was stolen", "hello", "what is this", "Any update?"]:
        for p in FakeIntentClassifier().predict([text]):
            assert {p.label, *(s.label for s in p.top_k)} <= INTENT_LABELS
            assert len(p.top_k) == 3 and p.top_k[0].label == p.label


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("My payment failed but the money was deducted.", "declined_card_payment"),
        ("When will my new card arrive?", "card_arrival"),
        ("My card was stolen yesterday", "lost_or_stolen_card"),
        ("I was charged twice for the same transaction", "transaction_charged_twice"),
        ("thanks!", "thank_you"),
    ],
)
def test_fake_intent_keywords(text, label):
    assert FakeIntentClassifier().predict([text])[0].label == label


def test_fake_intent_unknown_text_is_low_confidence_oos():
    p = FakeIntentClassifier().predict(["Any update?"])[0]
    assert p.label == "oos" and p.confidence < 0.5


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("My payment failed but the money was deducted.", "negative"),
        ("This is the worst bank I have ever used", "negative"),
        ("I love the new mobile banking features!", "positive"),
        ("I need to update my phone number on my account", "neutral"),
    ],
)
def test_fake_sentiment(text, label):
    p = FakeSentimentClassifier().predict([text])[0]
    assert p.label == label
    assert {s.label for s in p.top_k} == SENTIMENT_LABELS


def test_fake_negative_is_strong_enough_to_raise_priority():
    assert FakeSentimentClassifier().predict(["payment failed"])[0].confidence >= 0.70


def test_text_prep():
    assert for_intent("  hello \n\n  there  ") == "hello there"
    assert for_sentiment("@rahul see https://x.io/a now") == "@user see http now"


@pytest.mark.parametrize("text", ["Any update?", "My card was stolen", "hello"])
def test_fake_top_k_is_ranked_highest_first(text):
    for classifier in (FakeIntentClassifier(), FakeSentimentClassifier()):
        p = classifier.predict([text])[0]
        scores = [s.confidence for s in p.top_k]
        assert scores == sorted(scores, reverse=True), (classifier.name, scores)
        assert p.top_k[0].confidence == p.confidence
        assert sum(scores) <= 1.0 + 1e-9
