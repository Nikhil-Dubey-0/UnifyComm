"""Pretrained cardiffnlp/twitter-roberta-base-sentiment-latest (ARCHITECTURE §8.3).

Worker only. Loads the pinned copy from models/sentiment/hf (scripts/download_models.py).
The model card's preprocessing (@user / http) happens in app.ai.text_prep.for_sentiment.
"""

import json
import logging
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.ai.contracts import Prediction
from app.ai.local.common import (
    batches,
    configure_torch,
    predictions_from_logits,
    sha256_of,
)
from app.config import Settings

log = logging.getLogger(__name__)

MODEL_NAME = "cardiffnlp-twitter-roberta-base-sentiment-latest"
MAX_LENGTH = 256  # ARCHITECTURE §6.2
MANIFEST = "manifest.json"


class LocalSentimentClassifier:
    name = MODEL_NAME

    def __init__(self, model, tokenizer, version: str) -> None:
        self._model = model
        self._tokenizer = tokenizer
        self._id2label = {int(k): v.lower() for k, v in model.config.id2label.items()}
        self.version = version

    @classmethod
    def load(cls, settings: Settings) -> "LocalSentimentClassifier":
        return cls.from_dir(settings.sentiment_model_dir, num_threads=settings.torch_num_threads)

    @classmethod
    def from_dir(cls, model_dir: Path, *, num_threads: int = 4) -> "LocalSentimentClassifier":
        configure_torch(num_threads)
        manifest_path = model_dir / MANIFEST
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"sentiment model missing in {model_dir}; run scripts.download_models"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sha = sha256_of(model_dir / manifest["weights_file"])
        if sha != manifest["weights_sha256"]:
            raise ValueError(f"sentiment weights hash {sha[:12]} != manifest; download again")

        tokenizer = AutoTokenizer.from_pretrained(model_dir)
        model = AutoModelForSequenceClassification.from_pretrained(model_dir)
        model.eval()

        classifier = cls(model, tokenizer, version=sha[:12])
        classifier.predict(["warm up"])
        log.info("sentiment model loaded", extra={"dir": str(model_dir), "version": sha[:12]})
        return classifier

    def predict(self, texts: list[str]) -> list[Prediction]:
        out: list[Prediction] = []
        with torch.inference_mode():
            for chunk in batches(texts):
                enc = self._tokenizer(
                    chunk, padding=True, truncation=True, max_length=MAX_LENGTH, return_tensors="pt"
                )
                logits = self._model(**enc).logits
                out.extend(predictions_from_logits(logits, self._id2label))
        return out
