"""Shared helpers for the torch classifiers. Worker only (ARCHITECTURE D3)."""

import hashlib
import threading
from pathlib import Path

import torch
from transformers.utils import logging as hf_logging

from app.ai.contracts import LabelScore, Prediction

BATCH_SIZE = 16  # ARCHITECTURE §8.4
TOP_K = 3

_threads_lock = threading.Lock()
_threads_set = False


def configure_torch(num_threads: int) -> None:
    """Once per process: intra-op thread count, and no progress bars or load reports in
    the worker log. Both loaders verify the weights' sha256; intent also checks the
    state dict keys."""
    global _threads_set
    with _threads_lock:
        if not _threads_set:
            torch.set_num_threads(num_threads)
            hf_logging.set_verbosity_error()
            hf_logging.disable_progress_bar()
            _threads_set = True


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def batches(items: list[str], size: int = BATCH_SIZE) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def predictions_from_logits(logits: torch.Tensor, id2label: dict[int, str]) -> list[Prediction]:
    probs = torch.softmax(logits, dim=-1)
    values, indices = probs.topk(min(TOP_K, probs.shape[-1]), dim=-1)
    out = []
    for row_values, row_indices in zip(values.tolist(), indices.tolist(), strict=True):
        top = [
            LabelScore(label=id2label[i], confidence=round(v, 6))
            for v, i in zip(row_values, row_indices, strict=True)
        ]
        out.append(Prediction(label=top[0].label, confidence=top[0].confidence, top_k=top))
    return out
