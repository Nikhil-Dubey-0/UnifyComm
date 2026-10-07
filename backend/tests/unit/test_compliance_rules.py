"""One pass and one fail test per §7.6.2 rule, plus the full registry."""

from dataclasses import replace
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.compliance import rules
from app.compliance.engine import SendContext, evaluate
from app.enums import Channel, Consent, Purpose

IST = ZoneInfo("Asia/Kolkata")
NOON = datetime(2026, 10, 7, 12, 0, tzinfo=IST)

BASE = SendContext(
    channel=Channel.whatsapp,
    purpose=Purpose.service_reply,
    is_template=False,
    body="We are looking into your payment and will update you today.",
    consent=Consent.opted_in,
    dnd=False,
    now_local=NOON,
    last_inbound_on_channel_at=NOON - timedelta(hours=1),
)

promo_window = rules.make_promo_window(time(9, 0), time(21, 0))


def ctx(**changes) -> SendContext:
    return replace(BASE, **changes)


def test_base_context_passes_every_rule():
    decision = evaluate(BASE, rules.build_rules())
    assert decision.allowed
    assert [r.rule_id for r in decision.results] == [
        "consent.opt_out",
        "consent.proactive_requires_opt_in",
        "dnd.proactive",
        "time.promo_window",
        "whatsapp.session_window",
        "content.sensitive_data",
        "content.prohibited_claims",
        "content.length",
    ]


def test_rule_ids_are_unique_and_described():
    built = rules.build_rules()
    assert len({r.rule_id for r in built}) == len(built)
    assert all(r.description for r in built)


# consent.opt_out
def test_opt_out_blocks_any_purpose():
    for purpose in Purpose:
        result = rules.consent_opt_out(ctx(consent=Consent.opted_out, purpose=purpose))
        assert not result.passed
        assert result.reason == "Customer has opted out of WhatsApp messages."


def test_opt_out_passes_for_unknown_consent():
    assert rules.consent_opt_out(ctx(consent=Consent.unknown)).passed


# consent.proactive_requires_opt_in
@pytest.mark.parametrize("consent", [Consent.unknown, Consent.opted_out])
def test_proactive_without_opt_in_is_blocked(consent):
    result = rules.consent_proactive_requires_opt_in(
        ctx(purpose=Purpose.proactive, consent=consent, channel=Channel.sms)
    )
    assert not result.passed
    assert result.reason == "Proactive SMS messages need the customer's opt-in."


def test_proactive_with_opt_in_and_service_reply_without_pass():
    assert rules.consent_proactive_requires_opt_in(ctx(purpose=Purpose.proactive)).passed
    assert rules.consent_proactive_requires_opt_in(ctx(consent=Consent.unknown)).passed


# dnd.proactive
def test_dnd_blocks_proactive():
    result = rules.dnd_proactive(ctx(dnd=True, purpose=Purpose.proactive))
    assert not result.passed
    assert result.reason == "Customer is on DND. Only service replies are allowed."


def test_dnd_allows_service_replies():
    assert rules.dnd_proactive(ctx(dnd=True)).passed
    assert rules.dnd_proactive(ctx(purpose=Purpose.proactive)).passed


# time.promo_window
@pytest.mark.parametrize("hour,minute", [(8, 59), (21, 0), (23, 30), (2, 0)])
def test_proactive_outside_window_is_blocked(hour, minute):
    now = NOON.replace(hour=hour, minute=minute)
    result = promo_window(ctx(purpose=Purpose.proactive, now_local=now))
    assert not result.passed
    assert result.reason == "Proactive messages are allowed only between 09:00 and 21:00 IST."


@pytest.mark.parametrize("hour,minute", [(9, 0), (12, 0), (20, 59)])
def test_proactive_inside_window_passes(hour, minute):
    now = NOON.replace(hour=hour, minute=minute)
    assert promo_window(ctx(purpose=Purpose.proactive, now_local=now)).passed


def test_service_reply_at_night_passes_window():
    assert promo_window(ctx(now_local=NOON.replace(hour=23))).passed


def test_window_comes_from_settings_values():
    narrow = rules.make_promo_window(time(10, 0), time(11, 0))
    assert not narrow(ctx(purpose=Purpose.proactive)).passed


# whatsapp.session_window
@pytest.mark.parametrize("last", [None, NOON - timedelta(hours=24, seconds=1)])
def test_whatsapp_free_form_outside_24h_is_blocked(last):
    result = rules.whatsapp_session_window(ctx(last_inbound_on_channel_at=last))
    assert not result.passed
    assert "within 24 h" in result.reason


def test_whatsapp_inside_24h_template_and_other_channels_pass():
    assert rules.whatsapp_session_window(ctx()).passed
    assert rules.whatsapp_session_window(
        ctx(last_inbound_on_channel_at=NOON - timedelta(hours=23, minutes=59))
    ).passed
    template = ctx(last_inbound_on_channel_at=None, is_template=True)
    assert rules.whatsapp_session_window(template).passed
    assert rules.whatsapp_session_window(
        ctx(channel=Channel.sms, last_inbound_on_channel_at=None)
    ).passed


# content.sensitive_data
@pytest.mark.parametrize(
    "body,what",
    [
        ("Your card 4111 1111 1111 1111 is blocked.", "a card number"),
        ("Card 4111-1111-1111-1111 noted", "a card number"),
        ("Aadhaar 2345 6789 0123 is linked.", "an Aadhaar number"),
        ("Please share the OTP you received.", "a request for an OTP, PIN, CVV or password"),
        ("What is your PIN?", "a request for an OTP, PIN, CVV or password"),
        ("Kindly send us your CVV to verify.", "a request for an OTP, PIN, CVV or password"),
        ("Reply with your password", "a request for an OTP, PIN, CVV or password"),
    ],
)
def test_sensitive_data_is_blocked(body, what):
    result = rules.content_sensitive_data(ctx(body=body))
    assert not result.passed
    assert result.reason == f"Message contains or requests sensitive data ({what})."


@pytest.mark.parametrize(
    "body",
    [
        "Your reference is 4111 1111 1111 1112.",  # fails the Luhn check
        "Call us on +91 98765 43210.",
        "We will never ask for your OTP or PIN.",
        "Do not share your password with anyone.",
        "Please share your PIN code for the delivery address.",  # Indian postal PIN code
        "Your OTP has expired; a new one is on its way.",
        "Transaction 123456 was reversed.",
    ],
)
def test_ordinary_text_passes_sensitive_data(body):
    assert rules.content_sensitive_data(ctx(body=body)).passed


# content.prohibited_claims
@pytest.mark.parametrize(
    "body,phrase",
    [
        ("This plan offers guaranteed returns!", "guaranteed returns"),
        ("A Risk-Free investment for you", "Risk-Free"),
        ("100% guaranteed approval", "100% guaranteed"),
    ],
)
def test_prohibited_claims_are_blocked(body, phrase):
    result = rules.content_prohibited_claims(ctx(body=body))
    assert not result.passed
    assert result.reason == f"Message contains a prohibited claim: '{phrase}'."


def test_ordinary_text_passes_claims():
    assert rules.content_prohibited_claims(ctx(body="Returns depend on market risk.")).passed


# content.length
@pytest.mark.parametrize(
    "channel,body",
    [
        (Channel.whatsapp, ""),
        (Channel.whatsapp, "   \n "),
        (Channel.sms, 1_601),
        (Channel.whatsapp, 4_097),
        (Channel.email, 50_001),
    ],
)
def test_empty_or_too_long_is_blocked(channel, body):
    if isinstance(body, int):
        body = "x" * body
    result = rules.content_length(ctx(channel=channel, body=body))
    assert not result.passed
    assert result.reason == f"Message is empty or too long for {rules.CHANNEL_NAMES[channel]}."


@pytest.mark.parametrize(
    "channel,length", [(Channel.sms, 1_600), (Channel.whatsapp, 4_096), (Channel.email, 50_000)]
)
def test_length_at_the_limit_passes(channel, length):
    assert rules.content_length(ctx(channel=channel, body="x" * length)).passed


def test_demo_cases():
    """ARCHITECTURE §17 steps 4 and 5."""
    built = rules.build_rules()
    priya = evaluate(ctx(consent=Consent.opted_out), built)
    assert [r.rule_id for r in priya.results if not r.passed] == ["consent.opt_out"]

    amit = evaluate(
        ctx(
            channel=Channel.sms,
            purpose=Purpose.proactive,
            dnd=True,
            last_inbound_on_channel_at=None,
        ),
        built,
    )
    assert [r.rule_id for r in amit.results if not r.passed] == ["dnd.proactive"]
    amit_late = evaluate(
        ctx(
            channel=Channel.sms,
            purpose=Purpose.proactive,
            dnd=True,
            now_local=NOON.replace(hour=22),
        ),
        built,
    )
    assert [r.rule_id for r in amit_late.results if not r.passed] == [
        "dnd.proactive",
        "time.promo_window",
    ]
