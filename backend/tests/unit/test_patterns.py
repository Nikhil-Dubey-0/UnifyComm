"""Sensitive-data detection and PII redaction (ARCHITECTURE §7.6.2, §7.7)."""

import pytest

from app.compliance.patterns import find_sensitive, luhn_valid, redact


@pytest.mark.parametrize(
    "digits,valid",
    [
        ("4111111111111111", True),
        ("5500005555555559", True),
        ("378282246310005", True),  # Amex, 15 digits
        ("4111111111111112", False),
        ("1234567890123", False),
    ],
)
def test_luhn(digits, valid):
    assert luhn_valid(digits) is valid


def test_card_and_aadhaar_detection_do_not_overlap():
    # A grouped 16-digit card must not also count as an Aadhaar number.
    found = find_sensitive("card 4111 1111 1111 1111")
    assert (found.card_number, found.aadhaar) == (True, False)
    found = find_sensitive("aadhaar 234567890123")
    assert (found.card_number, found.aadhaar) == (False, True)


def test_aadhaar_needs_first_digit_2_to_9():
    assert not find_sensitive("id 123456789012").aadhaar
    assert not find_sensitive("id 0234 5678 9012").aadhaar


def test_phone_with_country_code_is_not_aadhaar():
    assert not find_sensitive("+919876543210").aadhaar


@pytest.mark.parametrize(
    "text,expected",
    [
        ("My card is 4111 1111 1111 1111", "My card is [CARD]"),
        ("Aadhaar 2345-6789-0123 please", "Aadhaar [AADHAAR] please"),
        ("Call me on +91 98765 43210 today", "Call me on [PHONE] today"),
        ("or 9876543210", "or [PHONE]"),
        ("mail rahul.sharma@example.com now", "mail [EMAIL] now"),
        ("My OTP is 482913", "My OTP is [CODE]"),
        ("pin: 1234", "pin: [CODE]"),
        ("482913 is the OTP", "[CODE] is the OTP"),
        ("CVV 123 and card 4111111111111111", "CVV [CODE] and card [CARD]"),
    ],
)
def test_redact(text, expected):
    assert redact(text) == expected


def test_redact_keeps_ordinary_numbers():
    text = "I was charged Rs 2,499 twice on 3 Oct for order 4521."
    assert redact(text) == text
