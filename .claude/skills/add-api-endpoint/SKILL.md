---
name: add-api-endpoint
description: Add or change a UnifyComm REST endpoint end to end (contract, schema, service, router, tests, OpenAPI export). Use for any change under backend/app/api or backend/app/schemas.
---

# Add an API endpoint

1. **Contract.** Add or change the row in ARCHITECTURE §10 (method, path, body/query, response). New events → §11; new job kinds → §12.
2. **Schema.** Pydantic v2 models in `backend/app/schemas/<area>.py`. ORM-backed outputs use `ConfigDict(from_attributes=True)`. Lists return `Page[T]` (`items`, `next_cursor`). Never return ORM objects.
3. **Service.** Logic and SQL in `backend/app/services/<area>.py`, taking `session: AsyncSession` as an argument. Raise domain errors from `app/errors.py` (`NotFound`, `Conflict`, `Unprocessable`, …) with a snake_case `code`. A service that owns the unit of work commits; emit events with `services/events.emit()` before that commit. Inserts that must be idempotent use `INSERT … ON CONFLICT`, never check-then-insert.
4. **Router.** `backend/app/api/<area>.py`: parse, auth (`CurrentAgent`), call the service, return the schema. No SQL, no business rules. Add `responses=ERROR_RESPONSES`. New routers are registered in `app/main.py:create_app`. Only login, webhooks, health and simulator inbound are unauthenticated.
5. **Tests.** `backend/tests/integration/test_*.py` with the `client`, `db`, `auth_headers`, `worker` fixtures; cover success, the error envelope (`{"error": {"code", "message"}}`) and auth. Use `run_all_jobs(worker)` for anything the worker finishes.
6. **Checks.** `cd backend; uv run ruff format .; uv run ruff check .; uv run pytest`.
7. **Export.** `uv run python -m scripts.export_openapi`, then (once the frontend exists) `cd frontend; npm run gen:api; npx tsc --noEmit`.
