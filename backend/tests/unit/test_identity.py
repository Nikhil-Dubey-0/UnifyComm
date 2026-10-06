import pytest

from app.enums import ContactKind
from app.services.identity import InvalidIdentifier, normalize, normalize_email, normalize_phone


@pytest.mark.parametrize(
    "raw",
    ["+91 98765 43210", "+919876543210", "09876543210", "98765 43210", "whatsapp:+919876543210"],
)
def test_phone_variants_normalize_to_e164(raw):
    assert normalize_phone(raw) == "+919876543210"


def test_whatsapp_prefix_is_case_insensitive():
    assert normalize_phone("WhatsApp:+91 99887 76655") == "+919988776655"


def test_foreign_number_keeps_country_code():
    assert normalize_phone("+1 415 523 8886") == "+14155238886"


@pytest.mark.parametrize("raw", ["", "abc", "12345", "+91 12345"])
def test_invalid_phone_rejected(raw):
    with pytest.raises(InvalidIdentifier):
        normalize_phone(raw)


def test_email_trimmed_and_lowercased_dots_kept():
    assert normalize_email("  Rahul.Sharma@Example.COM ") == "rahul.sharma@example.com"


@pytest.mark.parametrize("raw", ["", "no-at-sign", "a@b", "a b@c.com", "@example.com"])
def test_invalid_email_rejected(raw):
    with pytest.raises(InvalidIdentifier):
        normalize_email(raw)


def test_normalize_dispatches_on_kind():
    assert normalize(ContactKind.phone, "98765 43210") == "+919876543210"
    assert normalize(ContactKind.email, "X@Y.io") == "x@y.io"
