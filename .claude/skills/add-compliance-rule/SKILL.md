---
name: add-compliance-rule
description: Add or change a UnifyComm compliance rule (ARCHITECTURE §7.6) end to end - contract row, pure rule function, registry, pass and fail tests, agent-facing reason. Use for any change in backend/app/compliance.
---

# Add a compliance rule

The compliance engine is pure (CLAUDE.md rule 5): a rule is a function of `SendContext` that returns a `RuleResult`. No DB, no network, no clock reads, no settings reads.

1. **Contract.** Add the row to the ARCHITECTURE §7.6.2 table: rule ID (`area.name`), when it blocks, and the exact agent-facing reason text. If the rule needs data that `SendContext` lacks, add the field to the §7.6.2 `SendContext(...)` signature too.
2. **Context (only if needed).** Add the field to `SendContext` in `backend/app/compliance/engine.py`; fill it in `services/outbound.py:_context()` (the only place that reads the DB or clock for compliance). `audit_context()` stores every field except `body` in `compliance_checks.context`, so keep fields JSON-friendly and never add secrets.
3. **Rule.** Write `def my_rule(ctx: SendContext) -> RuleResult` in `backend/app/compliance/rules.py`. Use `_ok(rule_id)` / `_fail(rule_id, reason)`. Configurable values (like the promo window) come in through a factory called from `build_rules(...)`, whose arguments come from `Settings` in `app/main.py` and `worker/loop.py`. Text patterns shared with PII redaction belong in `compliance/patterns.py`.
4. **Register.** Add `Rule(rule_id, description, fn)` to `build_rules()` in table order. The description is shown by `GET /api/compliance/rules` and the compliance log filter.
5. **Unit tests.** In `backend/tests/unit/test_compliance_rules.py`: at least one failing case asserting the exact reason text and one passing case (include the boundary, e.g. 21:00 vs 20:59). Update `test_base_context_passes_every_rule` and `test_compliance_rules_endpoint` (integration) with the new ID.
6. **Integration.** If the rule depends on stored data (preferences, last inbound), add a case to `backend/tests/integration/test_compliance_flow.py` through the real send or outreach endpoint.
7. **Checks.** `cd backend; uv run ruff format .; uv run ruff check .; uv run pytest tests/unit tests/integration/test_compliance_flow.py`.
8. **UI.** Nothing to code: blocked messages show `reason` in the thread, the outreach dialog and `/admin/compliance`. Check the reason reads well there (short, one sentence, says what the agent can do).
