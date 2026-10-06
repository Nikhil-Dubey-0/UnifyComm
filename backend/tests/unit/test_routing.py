"""Category, sticky primary intent and priority (ARCHITECTURE §7.3–7.5)."""

import pytest

from app.ai.intent_map import get_intent_map
from app.enums import Priority
from app.services.routing import (
    IntentReading,
    RoutingState,
    SentimentReading,
    compute_priority,
    decide,
    is_substantive,
    needs_review,
    raise_one,
)

FLOOR = 0.50
MAP = get_intent_map()
EMPTY = RoutingState(None, None, None, Priority.normal)
NEG = SentimentReading("negative", 0.86)
NEUTRAL = SentimentReading("neutral", 0.9)


def test_needs_review_for_oos_or_low_confidence():
    assert needs_review(IntentReading("oos", 0.99), FLOOR)
    assert needs_review(IntentReading("card_arrival", 0.49), FLOOR)
    assert not needs_review(IntentReading("card_arrival", 0.50), FLOOR)


def test_small_talk_and_out_of_scope_are_not_substantive():
    assert not is_substantive(IntentReading("thank_you", 0.99), MAP, FLOOR)
    assert not is_substantive(IntentReading("weather", 0.99), MAP, FLOOR)
    assert is_substantive(IntentReading("card_arrival", 0.9), MAP, FLOOR)


def test_first_substantive_message_sets_category_and_intent():
    new = decide(EMPTY, IntentReading("declined_card_payment", 0.92), [NEUTRAL], MAP, FLOOR)
    assert new.category == "payments_billing"
    assert new.primary_intent == "declined_card_payment"
    assert new.primary_intent_confidence == 0.92


@pytest.mark.parametrize(
    "follow_up",
    [
        IntentReading("oos", 0.35),  # "Any update?"
        IntentReading("thank_you", 0.99),  # "thanks"
        IntentReading("card_arrival", 0.40),  # below the floor
        IntentReading("card_arrival", 0.80),  # substantive but less confident
        None,  # intent failed
    ],
)
def test_primary_intent_is_sticky(follow_up):
    current = RoutingState("payments_billing", "declined_card_payment", 0.92, Priority.normal)
    new = decide(current, follow_up, [NEUTRAL], MAP, FLOOR)
    assert (new.category, new.primary_intent) == ("payments_billing", "declined_card_payment")


def test_more_confident_substantive_message_replaces_primary_intent():
    current = RoutingState("payments_billing", "declined_card_payment", 0.70, Priority.normal)
    new = decide(current, IntentReading("lost_or_stolen_card", 0.95), [], MAP, FLOOR)
    assert (new.category, new.primary_intent, new.priority) == (
        "fraud_security",
        "lost_or_stolen_card",
        Priority.urgent,
    )


def test_needs_review_message_on_empty_conversation_sets_nothing():
    new = decide(EMPTY, IntentReading("oos", 0.9), [], MAP, FLOOR)
    assert new.category is None and new.primary_intent is None
    assert new.priority is Priority.low


@pytest.mark.parametrize(
    ("category", "sentiments", "expected"),
    [
        ("fraud_security", [], Priority.urgent),
        ("fraud_security", [NEG], Priority.urgent),
        ("payments_billing", [], Priority.normal),
        ("payments_billing", [NEG], Priority.high),  # demo step 1
        ("payments_billing", [NEUTRAL, NEUTRAL, NEG], Priority.high),
        ("payments_billing", [NEUTRAL, NEUTRAL, NEUTRAL, NEG], Priority.normal),  # only last 3
        ("payments_billing", [SentimentReading("negative", 0.69)], Priority.normal),
        ("general_banking", [], Priority.low),
        ("general_banking", [NEG], Priority.normal),
        (None, [], Priority.low),
        (None, [NEG], Priority.normal),
    ],
)
def test_priority_rules(category, sentiments, expected):
    assert compute_priority(category, sentiments, MAP) is expected


def test_raise_one_caps_at_urgent():
    assert raise_one(Priority.low) is Priority.normal
    assert raise_one(Priority.high) is Priority.urgent
    assert raise_one(Priority.urgent) is Priority.urgent
