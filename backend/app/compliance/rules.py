"""Rule registry (ARCHITECTURE §7.6.2). Every rule is a pure function of SendContext.

`build_rules` takes the promotional window from Settings so the rules never read config
or the clock themselves. Add a rule with the `add-compliance-rule` project skill.
"""

import re
from datetime import time, timedelta

from app.compliance import patterns
from app.compliance.engine import Rule, RuleResult, SendContext
from app.enums import Channel, Consent, Purpose

WHATSAPP_SESSION_WINDOW = timedelta(hours=24)

CHANNEL_LIMITS: dict[Channel, int] = {
    Channel.sms: 1_600,
    Channel.whatsapp: 4_096,
    Channel.email: 50_000,
}

CHANNEL_NAMES: dict[Channel, str] = {
    Channel.whatsapp: "WhatsApp",
    Channel.sms: "SMS",
    Channel.email: "email",
}

PROHIBITED_PHRASES = [
    "guaranteed returns",
    "guaranteed return",
    "100% guaranteed",
    "risk-free",
    "risk free",
    "assured returns",
    "double your money",
]
_PROHIBITED = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in PROHIBITED_PHRASES) + r")(?!\w)", re.IGNORECASE
)


def _ok(rule_id: str) -> RuleResult:
    return RuleResult(rule_id, True)


def _fail(rule_id: str, reason: str) -> RuleResult:
    return RuleResult(rule_id, False, reason)


def consent_opt_out(ctx: SendContext) -> RuleResult:
    rule_id = "consent.opt_out"
    if ctx.consent == Consent.opted_out:
        return _fail(rule_id, f"Customer has opted out of {CHANNEL_NAMES[ctx.channel]} messages.")
    return _ok(rule_id)


def consent_proactive_requires_opt_in(ctx: SendContext) -> RuleResult:
    rule_id = "consent.proactive_requires_opt_in"
    if ctx.purpose == Purpose.proactive and ctx.consent != Consent.opted_in:
        return _fail(
            rule_id, f"Proactive {CHANNEL_NAMES[ctx.channel]} messages need the customer's opt-in."
        )
    return _ok(rule_id)


def dnd_proactive(ctx: SendContext) -> RuleResult:
    rule_id = "dnd.proactive"
    if ctx.dnd and ctx.purpose == Purpose.proactive:
        return _fail(rule_id, "Customer is on DND. Only service replies are allowed.")
    return _ok(rule_id)


def make_promo_window(start: time, end: time):
    def promo_window(ctx: SendContext) -> RuleResult:
        rule_id = "time.promo_window"
        local = ctx.now_local.timetz().replace(tzinfo=None)
        if ctx.purpose == Purpose.proactive and not (start <= local < end):
            return _fail(
                rule_id,
                f"Proactive messages are allowed only between {start:%H:%M} and {end:%H:%M} IST.",
            )
        return _ok(rule_id)

    return promo_window


def whatsapp_session_window(ctx: SendContext) -> RuleResult:
    rule_id = "whatsapp.session_window"
    if ctx.channel != Channel.whatsapp or ctx.is_template:
        return _ok(rule_id)
    last = ctx.last_inbound_on_channel_at
    if last is None or ctx.now_local - last > WHATSAPP_SESSION_WINDOW:
        return _fail(
            rule_id,
            "WhatsApp free-form messages are allowed only within 24 h of the customer's "
            "last WhatsApp message.",
        )
    return _ok(rule_id)


def content_sensitive_data(ctx: SendContext) -> RuleResult:
    rule_id = "content.sensitive_data"
    found = patterns.find_sensitive(ctx.body).describe()
    if found:
        return _fail(rule_id, f"Message contains or requests sensitive data ({', '.join(found)}).")
    return _ok(rule_id)


def content_prohibited_claims(ctx: SendContext) -> RuleResult:
    rule_id = "content.prohibited_claims"
    m = _PROHIBITED.search(ctx.body)
    if m:
        return _fail(rule_id, f"Message contains a prohibited claim: '{m.group(1)}'.")
    return _ok(rule_id)


def content_length(ctx: SendContext) -> RuleResult:
    rule_id = "content.length"
    if not ctx.body.strip() or len(ctx.body) > CHANNEL_LIMITS[ctx.channel]:
        return _fail(rule_id, f"Message is empty or too long for {CHANNEL_NAMES[ctx.channel]}.")
    return _ok(rule_id)


def build_rules(promo_start: time = time(9, 0), promo_end: time = time(21, 0)) -> list[Rule]:
    """The §7.6.2 rules in table order."""
    return [
        Rule(
            "consent.opt_out",
            "Blocks any message on a channel the customer opted out of.",
            consent_opt_out,
        ),
        Rule(
            "consent.proactive_requires_opt_in",
            "Proactive messages need the customer's opt-in on that channel.",
            consent_proactive_requires_opt_in,
        ),
        Rule(
            "dnd.proactive",
            "Customers on DND receive service replies only.",
            dnd_proactive,
        ),
        Rule(
            "time.promo_window",
            f"Proactive messages only between {promo_start:%H:%M} and {promo_end:%H:%M} IST "
            "(TRAI TCCCPR).",
            make_promo_window(promo_start, promo_end),
        ),
        Rule(
            "whatsapp.session_window",
            "WhatsApp free-form messages only within 24 h of the customer's last WhatsApp "
            "message; templates are exempt.",
            whatsapp_session_window,
        ),
        Rule(
            "content.sensitive_data",
            "Blocks card numbers, Aadhaar numbers and requests for OTP, PIN, CVV or password.",
            content_sensitive_data,
        ),
        Rule(
            "content.prohibited_claims",
            "Blocks prohibited claims such as 'guaranteed returns' or 'risk-free'.",
            content_prohibited_claims,
        ),
        Rule(
            "content.length",
            "Blocks empty messages and messages over the channel limit "
            "(SMS 1,600, WhatsApp 4,096, email 50,000 characters).",
            content_length,
        ),
    ]
