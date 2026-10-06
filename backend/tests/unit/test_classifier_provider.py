"""Model loading in the worker: fake mode, failure isolation, retry cooldown (§3, §14)."""

import pytest

from app.ai.fake import FakeIntentClassifier, FakeSentimentClassifier
from app.enums import AiTask
from app.worker import classifiers
from app.worker.classifiers import ClassifierProvider, ModelUnavailable


def test_fake_mode_returns_fake_classifiers(settings):
    provider = ClassifierProvider(settings)
    assert isinstance(provider.get(AiTask.intent), FakeIntentClassifier)
    assert isinstance(provider.get(AiTask.sentiment), FakeSentimentClassifier)
    assert provider.get(AiTask.intent) is provider.get(AiTask.intent)


def test_failed_load_is_cached_then_retried(settings, monkeypatch):
    provider = ClassifierProvider(settings)
    calls = []

    def broken(task):
        calls.append(task)
        raise FileNotFoundError("weights missing")

    monkeypatch.setattr(provider, "_load", broken)
    clock = [1000.0]
    monkeypatch.setattr(classifiers.time, "monotonic", lambda: clock[0])

    with pytest.raises(ModelUnavailable, match="weights missing"):
        provider.get(AiTask.intent)
    with pytest.raises(ModelUnavailable):
        provider.get(AiTask.intent)  # within the cooldown: no second load attempt
    assert calls == [AiTask.intent]
    assert provider.describe(AiTask.intent) == ("intent-unavailable", "none")

    clock[0] += classifiers.RETRY_LOAD_SECONDS + 1
    monkeypatch.setattr(provider, "_load", lambda task: FakeIntentClassifier())
    assert isinstance(provider.get(AiTask.intent), FakeIntentClassifier)


def test_preload_swallows_failures(settings, monkeypatch):
    provider = ClassifierProvider(settings)

    def load(task):
        if task is AiTask.intent:
            raise RuntimeError("boom")
        return FakeSentimentClassifier()

    monkeypatch.setattr(provider, "_load", load)
    provider.preload()
    assert isinstance(provider.get(AiTask.sentiment), FakeSentimentClassifier)
    with pytest.raises(ModelUnavailable):
        provider.get(AiTask.intent)
