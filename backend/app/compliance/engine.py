"""Compliance engine (ARCHITECTURE §7.6). Pure: no DB, no network, no clock reads.

Callers build a SendContext (with `now_local` passed in) and store the results.
"""

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from app.enums import Channel, Consent, Purpose


@dataclass(frozen=True)
class SendContext:
    channel: Channel
    purpose: Purpose
    is_template: bool
    body: str
    consent: Consent
    dnd: bool
    now_local: datetime
    last_inbound_on_channel_at: datetime | None

    def audit_context(self) -> dict[str, Any]:
        """What compliance_checks.context records (no message body)."""
        data = asdict(self)
        data.pop("body")
        data["now_local"] = self.now_local.isoformat()
        last = self.last_inbound_on_channel_at
        data["last_inbound_on_channel_at"] = last.isoformat() if last else None
        return {k: (str(v) if hasattr(v, "value") else v) for k, v in data.items()}


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    passed: bool
    reason: str | None = None


@dataclass(frozen=True)
class Rule:
    rule_id: str
    description: str
    check: Callable[[SendContext], RuleResult]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    results: list[RuleResult]


def evaluate(ctx: SendContext, rules: Sequence[Rule]) -> Decision:
    """Run every rule (no short-circuit) so the audit log records all outcomes."""
    results = [rule.check(ctx) for rule in rules]
    return Decision(allowed=all(r.passed for r in results), results=results)
