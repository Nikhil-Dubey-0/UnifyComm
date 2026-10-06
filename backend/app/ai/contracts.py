"""Classifier contracts (ARCHITECTURE §8.1). Torch-free: imported by the api and the worker."""

from typing import Protocol

from pydantic import BaseModel


class LabelScore(BaseModel):
    label: str
    confidence: float


class Prediction(BaseModel):
    label: str
    confidence: float  # 0..1, softmax probability of `label`
    top_k: list[LabelScore]  # 3 entries, highest first


class TextClassifier(Protocol):
    name: str
    version: str

    def predict(self, texts: list[str]) -> list[Prediction]: ...
