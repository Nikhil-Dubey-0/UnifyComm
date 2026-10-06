"""Classifier selection for the worker (AI_MODE=fake|real).

Real models are imported lazily on first use, so the worker imports torch only in real
mode (ARCHITECTURE D3). A model that fails to load yields per-task errors (§14) and is
retried on the next job.
"""

import logging
import threading

from app.ai.contracts import TextClassifier
from app.ai.fake import FakeIntentClassifier, FakeSentimentClassifier
from app.config import Settings
from app.enums import AiTask

log = logging.getLogger(__name__)


class ModelUnavailable(Exception):
    pass


class ClassifierProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._loaded: dict[AiTask, TextClassifier] = {}
        self._lock = threading.Lock()

    def get(self, task: AiTask) -> TextClassifier:
        """Called from a worker thread (asyncio.to_thread); loading is serialized."""
        with self._lock:
            if task not in self._loaded:
                self._loaded[task] = self._load(task)
            return self._loaded[task]

    def _load(self, task: AiTask) -> TextClassifier:
        if self._settings.ai_mode == "fake":
            return FakeIntentClassifier() if task is AiTask.intent else FakeSentimentClassifier()
        # Session 3 provides app.ai.local.intent / app.ai.local.sentiment.
        try:
            if task is AiTask.intent:
                from app.ai.local.intent import (
                    LocalIntentClassifier,  # type: ignore[import-not-found]
                )

                return LocalIntentClassifier.load(self._settings)
            from app.ai.local.sentiment import (
                LocalSentimentClassifier,  # type: ignore[import-not-found]
            )

            return LocalSentimentClassifier.load(self._settings)
        except Exception as exc:
            log.exception("model failed to load", extra={"task": str(task)})
            raise ModelUnavailable(f"{task} model unavailable: {exc}") from exc

    def describe(self, task: AiTask) -> tuple[str, str]:
        """(model_name, model_version) for an error row when the model never loaded."""
        loaded = self._loaded.get(task)
        if loaded is not None:
            return loaded.name, loaded.version
        return f"{task}-unavailable", "none"
