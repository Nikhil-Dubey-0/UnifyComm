"""Sensitive-data patterns shared by the `content.sensitive_data` rule (ARCHITECTURE §7.6.2)
and PII redaction before LLM calls (§7.7). Pure: regular expressions and arithmetic only.
"""

import re
from dataclasses import dataclass

# 13–19 digits, optionally grouped by single spaces or hyphens ("4111 1111 1111 1111").
_CARD_CANDIDATE = re.compile(r"(?<![\d+])\d(?:[ -]?\d){12,18}(?!\d)")
# Aadhaar format: 12 digits, first digit 2–9, contiguous or grouped 4-4-4. The lookarounds
# stop it matching 12 digits inside a longer grouped number.
_AADHAAR = re.compile(r"(?<![\d+])(?<!\d[ -])[2-9]\d{3}([ -]?)\d{4}\1\d{4}(?![ -]?\d)")
# Phone numbers: optional +country code, then 10 digits with optional separators.
_PHONE = re.compile(r"(?<![\w+])(?:\+\d{1,3}[ -]?)?(?:\d[ -]?){9}\d(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

_SECRET = r"(?:otp|one[- ]time (?:password|code)|pin(?!\s*-?\s*code)|cvv|cvc|password|passcode)"
# A 3–8 digit code (CVVs have 3) next to OTP/PIN/CVV, in either order:
# "OTP is 482913", "482913 is the OTP".
_CODE_AFTER = re.compile(rf"(\b{_SECRET}\b[^\d\n]{{0,15}}?)(\d{{3,8}})(?!\d)", re.IGNORECASE)
_CODE_BEFORE = re.compile(
    rf"(?<!\d)(\d{{3,8}})(\s*(?:is\s+)?(?:your|my|the)?\s*{_SECRET}\b)", re.IGNORECASE
)

# Asking the customer for a secret: "share your OTP", "what is your PIN", "send the CVV".
_REQUEST_VERB = (
    r"(?:share|send|tell|provide|give|enter|confirm|type|reply with|ask(?:ing)? for|need|"
    r"verify|forward|read out|mention)"
)
_SECRET_REQUEST = re.compile(
    rf"\b{_REQUEST_VERB}\b(?:\W+\w+){{0,4}}?\W+{_SECRET}\b"
    rf"|\bwhat(?:'s|\s+is)\s+(?:your|the)\s+{_SECRET}\b",
    re.IGNORECASE,
)
# "We will never ask for your OTP" is a warning, not a request.
_NEGATION = re.compile(r"\b(?:never|not|don'?t|do not|won'?t|will not|no one|nobody)\b[^.!?\n]*$")


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _card_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for m in _CARD_CANDIDATE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and luhn_valid(digits):
            spans.append(m.span())
    return spans


def _replace_spans(text: str, spans: list[tuple[int, int]], token: str) -> str:
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + token + text[end:]
    return text


def _secret_requests(text: str) -> list[str]:
    found = []
    for m in _SECRET_REQUEST.finditer(text):
        before = text[max(0, m.start() - 40) : m.start()]
        if not _NEGATION.search(before):
            found.append(m.group())
    return found


@dataclass(frozen=True)
class SensitiveFindings:
    card_number: bool
    aadhaar: bool
    secret_request: bool

    def describe(self) -> list[str]:
        """Agent-facing names of what was found, for the rule's reason text."""
        names = []
        if self.card_number:
            names.append("a card number")
        if self.aadhaar:
            names.append("an Aadhaar number")
        if self.secret_request:
            names.append("a request for an OTP, PIN, CVV or password")
        return names


def find_sensitive(text: str) -> SensitiveFindings:
    without_cards = _replace_spans(text, _card_spans(text), "[CARD]")
    return SensitiveFindings(
        card_number=without_cards != text,
        aadhaar=bool(_AADHAAR.search(without_cards)),
        secret_request=bool(_secret_requests(text)),
    )


def redact(text: str) -> str:
    """§7.7: card → [CARD], Aadhaar → [AADHAAR], phone → [PHONE], email → [EMAIL],
    OTP/PIN/CVV codes → [CODE]. Order matters: longer digit runs are replaced first."""
    text = _replace_spans(text, _card_spans(text), "[CARD]")
    text = _AADHAAR.sub("[AADHAAR]", text)
    text = _EMAIL.sub("[EMAIL]", text)
    text = _CODE_AFTER.sub(lambda m: m.group(1) + "[CODE]", text)
    text = _CODE_BEFORE.sub(lambda m: "[CODE]" + m.group(2), text)
    return _PHONE.sub("[PHONE]", text)
