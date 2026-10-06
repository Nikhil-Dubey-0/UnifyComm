"""Loads config/intent_map.yaml: intent label → routing category (ARCHITECTURE §7.3)."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import CONFIG_DIR
from app.enums import Priority

INTENT_MAP_PATH = CONFIG_DIR / "intent_map.yaml"
OOS_LABEL = "oos"


@dataclass(frozen=True)
class Category:
    key: str
    queue: str | None
    substantive: bool
    default_priority: Priority


@dataclass(frozen=True)
class IntentMap:
    categories: dict[str, Category]
    label_to_category: dict[str, str]

    def category_of(self, label: str) -> Category | None:
        key = self.label_to_category.get(label)
        return self.categories[key] if key else None


def parse_intent_map(raw: dict) -> IntentMap:
    categories = {
        key: Category(
            key=key,
            queue=spec["queue"],
            substantive=bool(spec["substantive"]),
            default_priority=Priority(spec["default_priority"]),
        )
        for key, spec in raw["categories"].items()
    }
    label_to_category: dict[str, str] = {}
    for category, labels in raw["labels"].items():
        if category not in categories:
            raise ValueError(f"intent_map: unknown category {category!r}")
        for label in labels:
            if label in label_to_category:
                raise ValueError(f"intent_map: label {label!r} is mapped twice")
            label_to_category[str(label)] = category
    return IntentMap(categories=categories, label_to_category=label_to_category)


def load_intent_map(path: Path = INTENT_MAP_PATH) -> IntentMap:
    with path.open(encoding="utf-8") as f:
        return parse_intent_map(yaml.safe_load(f))


@lru_cache
def get_intent_map() -> IntentMap:
    return load_intent_map()
