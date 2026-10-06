"""Classifier selection for the worker (AI_MODE=fake|real).

Real models are imported only when loaded, so the worker imports torch only in real mode
(ARCHITECTURE D3). In real mode the worker preloads them at startup (§3). A model that
fails to load yields per-task errors (§14); loading is retried at most once per
RETRY_LOAD_SECONDS so a missing model does not slow every job.
"""

import logging
import threading
import time

from app.ai.contracts import TextClassifier
from app.ai.fake import FakeIntentClassifier, FakeSentimentClassifier
from app.config import Settings
from app.enums import AiTask

log = logging.getLogger(__name__)

RETRY_LOAD_SECONDS = 60.0


class ModelUnavailable(Exception):
    pass


class ClassifierProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._loaded: dict[AiTask, TextClassifier] = {}
        self._failed: dict[AiTask, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, task: AiTask) -> TextClassifier:
        """Called from worker threads (asyncio.to_thread); loading is serialized."""
        with self._lock:
            if task in self._loaded:
                return self._loaded[task]
            failed = self._failed.get(task)
            if failed and time.monotonic() - failed[0] < RETRY_LOAD_SECONDS:
                raise ModelUnavailable(failed[1])
            try:
                self._loaded[task] = self._load(task)
            except Exception as exc:
                message = f"{task} model unavailable: {type(exc).__name__}: {exc}"
                self._failed[task] = (time.monotonic(), message)
                log.exception("model failed to load", extra={"task": str(task)})
                raise ModelUnavailable(message) from exc
            self._failed.pop(task, None)
            return self._loaded[task]

    def preload(self) -> None:
        """Load every model now (worker startup in real mode). Failures are logged."""
        for task in AiTask:
            try:
                self.get(task)
            except ModelUnavailable:
                pass

    def _load(self, task: AiTask) -> TextClassifier:
        if self._settings.ai_mode == "fake":
            return FakeIntentClassifier() if task is AiTask.intent else FakeSentimentClassifier()
        started = time.perf_counter()
        if task is AiTask.intent:
            from app.ai.local.intent import LocalIntentClassifier

            classifier: TextClassifier = LocalIntentClassifier.load(self._settings)
        else:
            from app.ai.local.sentiment import LocalSentimentClassifier

            classifier = LocalSentimentClassifier.load(self._settings)
        log.info(
            "model ready",
            extra={"task": str(task), "load_s": round(time.perf_counter() - started, 1)},
        )
        return classifier

    def describe(self, task: AiTask) -> tuple[str, str]:
        """(model_name, model_version) for an error row when the model never loaded."""
        loaded = self._loaded.get(task)
        if loaded is not None:
            return loaded.name, loaded.version
        return f"{task}-unavailable", "none"
