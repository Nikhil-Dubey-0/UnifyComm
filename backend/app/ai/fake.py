"""Keyword predictors for AI_MODE=fake (ARCHITECTURE §8.1). Torch-free.

Labels come from the real label sets so routing behaves the same as with the real models.
"""

import re

from app.ai.contracts import LabelScore, Prediction

FAKE_VERSION = "fake-1"

# (pattern, label), first match wins. Ordered from most to least specific.
INTENT_RULES: list[tuple[str, str]] = [
    (r"\b(stolen|lost my card|card (was|is|got) lost)\b", "lost_or_stolen_card"),
    (r"\b(fraud|scam|unauthori[sz]ed|didn'?t make|don'?t recogni[sz]e)\b", "report_fraud"),
    (r"\b(charged twice|double charged|charged two times)\b", "transaction_charged_twice"),
    (r"\brefund\b", "request_refund"),
    (r"\b(payment (failed|declined)|deducted|declined)\b", "declined_card_payment"),
    (r"\btop[- ]?up\b", "top_up_failed"),
    (r"\btransfer\b", "pending_transfer"),
    (r"\b(new card|card (arrive|arrival|delivery)|my card (come|arrive))", "card_arrival"),
    (r"\bpin\b", "change_pin"),
    (
        r"\b(blocked|locked out|can'?t (access|log ?in)|cannot (access|log ?in))\b",
        "account_blocked",
    ),
    (r"\b(loan|emi|interest rate)\b", "interest_rate"),
    (r"\bcredit limit\b", "credit_limit"),
    (r"\bexchange rate\b", "exchange_rate"),
    (r"\b(thanks|thank you)\b", "thank_you"),
    (r"^\s*(hi|hello|hey)\b", "greeting"),
    (r"\b(bye|goodbye)\b", "goodbye"),
    (r"\bweather\b", "weather"),
    (r"\bflight\b", "book_flight"),
]

# Runner-up labels for top_k; all exist in id2label.json.
_INTENT_FILLERS = ["oos", "greeting", "thank_you"]

NEGATIVE_WORDS = (
    r"\b(failed|deducted|worst|terrible|awful|angry|frustrat\w*|not working|stolen|fraud|"
    r"nobody|useless|charged twice|still waiting|disappointed|scam|ridiculous|blocked)\b"
)
POSITIVE_WORDS = r"\b(thanks|thank you|great|love|awesome|happy|resolved|perfect|excellent)\b"


def _top_k(label: str, confidence: float, fillers: list[str]) -> list[LabelScore]:
    """Runner-ups share the remaining probability but always rank below `label`."""
    others = [f for f in fillers if f != label][:2]
    rest = 1.0 - confidence
    second = round(min(rest * 0.6, confidence * 0.8), 4)
    third = round(min(rest - second, second * 0.75), 4)
    return [
        LabelScore(label=label, confidence=confidence),
        LabelScore(label=others[0], confidence=second),
        LabelScore(label=others[1], confidence=third),
    ]


class FakeIntentClassifier:
    name = "fake-intent"
    version = FAKE_VERSION

    def predict(self, texts: list[str]) -> list[Prediction]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> Prediction:
        lowered = text.lower()
        for pattern, label in INTENT_RULES:
            if re.search(pattern, lowered):
                conf = 0.92
                return Prediction(
                    label=label, confidence=conf, top_k=_top_k(label, conf, _INTENT_FILLERS)
                )
        # No keyword: low-confidence oos, which the app treats as "Needs review".
        conf = 0.35
        return Prediction(
            label="oos", confidence=conf, top_k=_top_k("oos", conf, ["greeting", "thank_you"])
        )


class FakeSentimentClassifier:
    name = "fake-sentiment"
    version = FAKE_VERSION

    def predict(self, texts: list[str]) -> list[Prediction]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> Prediction:
        lowered = text.lower()
        if re.search(NEGATIVE_WORDS, lowered):
            label, conf = "negative", 0.86
        elif re.search(POSITIVE_WORDS, lowered):
            label, conf = "positive", 0.88
        else:
            label, conf = "neutral", 0.72
        return Prediction(
            label=label,
            confidence=conf,
            top_k=_top_k(label, conf, ["negative", "neutral", "positive"]),
        )
