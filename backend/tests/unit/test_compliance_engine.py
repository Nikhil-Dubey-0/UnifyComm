"""The engine skeleton: pure evaluation over a rule registry (ARCHITECTURE §7.6)."""

from datetime import UTC, datetime

from app.compliance.engine import Rule, RuleResult, SendContext, evaluate
from app.compliance.rules import RULES
from app.enums import Channel, Consent, Purpose

CTX = SendContext(
    channel=Channel.whatsapp,
    purpose=Purpose.service_reply,
    is_template=False,
    body="secret body",
    consent=Consent.opted_in,
    dnd=False,
    now_local=datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
    last_inbound_on_channel_at=None,
)


def _rule(rule_id: str, passed: bool) -> Rule:
    return Rule(
        rule_id,
        f"{rule_id} rule",
        lambda _ctx: RuleResult(rule_id, passed, None if passed else "no"),
    )


def test_empty_registry_allows():
    assert RULES == []
    decision = evaluate(CTX, RULES)
    assert decision.allowed and decision.results == []


def test_any_failure_blocks_and_all_rules_still_run():
    decision = evaluate(CTX, [_rule("a", False), _rule("b", True), _rule("c", False)])
    assert not decision.allowed
    assert [(r.rule_id, r.passed) for r in decision.results] == [
        ("a", False),
        ("b", True),
        ("c", False),
    ]


def test_audit_context_excludes_body_and_is_json_ready():
    ctx = CTX.audit_context()
    assert "body" not in ctx
    assert ctx["channel"] == "whatsapp" and ctx["consent"] == "opted_in"
    assert ctx["now_local"].startswith("2026-10-06T12:00")
