---
name: db-migration
description: Change the UnifyComm database schema safely. Use whenever a table, column, index, CHECK constraint or enum value changes (ORM in backend/app/models, Alembic in backend/migrations).
---

# Database migration

ARCHITECTURE.md §5 is the contract. Change it first, then the code.

1. **Contract.** Edit ARCHITECTURE §5 (tables, notes, state machines). New enum values also go in `backend/app/enums.py`; the ORM's `enum_check()` turns them into CHECK constraints.
2. **ORM.** Edit `backend/app/models/*.py`. Conventions:
   - `pk()`, `created_at()`, `updated_at()` helpers from `models/base.py`.
   - Enum-like columns are `Text` + `enum_check(column, Enum)`. Never Postgres enums.
   - Confidence-like floats use `REAL()` (not `Float(precision=…)`, which autogenerate reports as drift).
   - Partial unique indexes use `Index(..., unique=True, postgresql_where=text("..."))`.
   - Cyclic FKs (e.g. `messages.draft_id ↔ reply_drafts`) are added with `op.create_foreign_key` after both tables exist.
3. **Generate.** `cd backend; uv run alembic revision --autogenerate -m "<what changed>"`.
4. **Review the file by hand.** Check partial-index `WHERE` clauses, CHECK constraints, `ondelete`, server defaults, and that `downgrade()` reverses everything in the right order. Data migrations need explicit SQL.
5. **Round-trip.** `uv run alembic upgrade head; uv run alembic downgrade -1; uv run alembic upgrade head; uv run alembic check` (the last must say "No new upgrade operations detected").
6. **Tests.** `uv run pytest` (the integration fixture also runs upgrade → downgrade base → upgrade on the test DB). Add a test for any new constraint.
7. **Seed/export.** If seed data or API schemas changed: `uv run python -m scripts.seed --reset`, `uv run python -m scripts.export_openapi`.
