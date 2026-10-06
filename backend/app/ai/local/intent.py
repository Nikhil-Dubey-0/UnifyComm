"""The team's intent model, repro-v1 (ARCHITECTURE §8.2). Worker only.

Mirrors ml/intent/verify_export.py exactly: MiniLM-L6 encoder, attention-masked mean
pooling, Dropout(0.1), Linear(384, 213); `clean_text` before tokenizing; padding to
max_length 64. Changing any of these changes predictions.
"""

import json
import logging
from pathlib import Path

import torch
import torch.nn as nn
from safetensors.torch import load_file
from transformers import AutoConfig, AutoModel, AutoTokenizer

from app.ai.contracts import Prediction
from app.ai.local.common import (
    batches,
    configure_torch,
    predictions_from_logits,
    sha256_of,
)
from app.ai.text_prep import clean_text
from app.config import Settings

log = logging.getLogger(__name__)

MODEL_NAME = "unifycomm-intent-minilm-l6-213"
WEIGHTS_FILE = "model.safetensors"


class IntentNetwork(nn.Module):
    def __init__(self, encoder: nn.Module, num_labels: int, dropout_rate: float) -> None:
        super().__init__()
        self.encoder = encoder
        self.dropout = nn.Dropout(dropout_rate)
        self.classifier = nn.Linear(encoder.config.hidden_size, num_labels)

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        hidden = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        mask = attention_mask.unsqueeze(-1).float()
        pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        return self.classifier(self.dropout(pooled))


class LocalIntentClassifier:
    name = MODEL_NAME

    def __init__(
        self,
        network: IntentNetwork,
        tokenizer,
        id2label: dict[int, str],
        max_length: int,
        version: str,
    ) -> None:
        self._network = network
        self._tokenizer = tokenizer
        self._id2label = id2label
        self._max_length = max_length
        self.version = version

    @classmethod
    def load(cls, settings: Settings) -> "LocalIntentClassifier":
        model_dir = settings.resolve_path(settings.intent_model_dir)
        return cls.from_dir(model_dir, num_threads=settings.torch_num_threads)

    @classmethod
    def from_dir(cls, model_dir: Path, *, num_threads: int = 4) -> "LocalIntentClassifier":
        configure_torch(num_threads)
        meta = json.loads((model_dir / "model_meta.json").read_text(encoding="utf-8"))
        weights = model_dir / WEIGHTS_FILE
        if not weights.exists():
            raise FileNotFoundError(f"intent weights missing: {weights}")
        sha = sha256_of(weights)
        expected = meta.get("weights_sha256")
        if expected and sha != expected:
            raise ValueError(f"intent weights hash {sha[:12]} != model_meta {expected[:12]}")

        id2label = {
            int(k): v
            for k, v in json.loads(
                (model_dir / "id2label.json").read_text(encoding="utf-8")
            ).items()
        }
        config = AutoConfig.from_pretrained(model_dir)
        network = IntentNetwork(
            AutoModel.from_config(config), meta["num_labels"], meta["dropout_rate"]
        )
        missing, unexpected = network.load_state_dict(load_file(weights), strict=False)
        missing = [k for k in missing if not k.endswith("position_ids")]
        if missing or unexpected:
            raise ValueError(
                f"intent state dict mismatch: missing={missing} unexpected={unexpected}"
            )
        network.eval()
        tokenizer = AutoTokenizer.from_pretrained(model_dir)

        classifier = cls(network, tokenizer, id2label, meta["max_length"], version=sha[:12])
        classifier.predict(["warm up"])
        log.info("intent model loaded", extra={"dir": str(model_dir), "version": sha[:12]})
        return classifier

    def predict(self, texts: list[str]) -> list[Prediction]:
        out: list[Prediction] = []
        with torch.inference_mode():
            for chunk in batches([clean_text(t) for t in texts]):
                enc = self._tokenizer(
                    chunk,
                    padding="max_length",
                    truncation=True,
                    max_length=self._max_length,
                    return_tensors="pt",
                )
                logits = self._network(enc["input_ids"], enc["attention_mask"])
                out.extend(predictions_from_logits(logits, self._id2label))
        return out
