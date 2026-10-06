"""Contract: every model label maps to exactly one category (ARCHITECTURE §7.3)."""

import json

import pytest
import yaml

from app.ai.intent_map import INTENT_MAP_PATH, get_intent_map, parse_intent_map
from app.config import REPO_ROOT
from app.enums import Priority

ID2LABEL_FILES = [
    REPO_ROOT / "models/intent/repro-v1/id2label.json",
    REPO_ROOT / "models/intent/final_model/id2label.json",
]
EXPECTED_CATEGORIES = {
    "fraud_security",
    "payments_billing",
    "transfers_topups",
    "cards",
    "account_access",
    "loans_credit",
    "general_banking",
    "small_talk",
    "out_of_scope",
}


@pytest.mark.parametrize("path", ID2LABEL_FILES, ids=lambda p: p.parent.name)
def test_every_model_label_has_exactly_one_category(path):
    labels = set(json.loads(path.read_text(encoding="utf-8")).values())
    assert len(labels) == 213
    mapped = set(get_intent_map().label_to_category)
    assert labels - mapped == set(), "labels missing from intent_map.yaml"
    assert mapped - labels == set(), "intent_map.yaml has labels the model does not know"


def test_yaml_lists_each_label_once():
    raw = yaml.safe_load(INTENT_MAP_PATH.read_text(encoding="utf-8"))
    all_labels = [label for labels in raw["labels"].values() for label in labels]
    assert len(all_labels) == len(set(all_labels))
    assert all(isinstance(label, str) for label in all_labels), "unquoted yes/no became bool"


def test_categories_match_architecture():
    m = get_intent_map()
    assert set(m.categories) == EXPECTED_CATEGORIES
    assert m.categories["fraud_security"].default_priority is Priority.urgent
    assert not m.categories["small_talk"].substantive
    assert not m.categories["out_of_scope"].substantive
    assert m.category_of("oos").key == "out_of_scope"


@pytest.mark.parametrize(
    ("label", "category"),
    [
        ("lost_or_stolen_card", "fraud_security"),
        ("transaction_charged_twice", "payments_billing"),
        ("pending_transfer", "transfers_topups"),
        ("card_arrival", "cards"),
        ("account_blocked", "account_access"),
        ("interest_rate", "loans_credit"),
        ("exchange_rate", "general_banking"),
        ("thank_you", "small_talk"),
        ("weather", "out_of_scope"),
    ],
)
def test_architecture_examples(label, category):
    assert get_intent_map().label_to_category[label] == category


def test_duplicate_label_is_rejected():
    raw = {
        "categories": {
            "a": {"queue": "A", "substantive": True, "default_priority": "normal"},
            "b": {"queue": "B", "substantive": True, "default_priority": "normal"},
        },
        "labels": {"a": ["x"], "b": ["x"]},
    }
    with pytest.raises(ValueError, match="mapped twice"):
        parse_intent_map(raw)
