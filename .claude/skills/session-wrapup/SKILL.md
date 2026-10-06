---
name: session-wrapup
description: Finish a UnifyComm build session - run every check, verify the session's exit criteria for real, update CLAUDE.md Status and ARCHITECTURE.md, and commit. Use at the end of each session or when asked to wrap up.
---

# Session wrap-up

1. **Backend checks** (from `backend/`): `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run alembic check`.
2. **Frontend checks** (from Session 2, in `frontend/`): `npm run gen:api`, `npx tsc --noEmit`, `npm run build`, `npx playwright test`.
3. **Exit criteria.** Run the session's exit criteria from ARCHITECTURE §16 against real processes, not by inference. For Session 1: start `uv run uvicorn app.main:app --port 8000` and `uv run python -m app.worker`, then `uv run python -m scripts.check_walking_skeleton`. Stop the processes afterwards.
4. **Logs.** Skim the api and worker logs: no tracebacks, no message bodies, no secrets or tokens.
5. **Docs.**
   - Tick finished items in ARCHITECTURE §16; record any contract change in the relevant section.
   - Update the Status block in `CLAUDE.md`: tick the session, list carry-over, and note anything the next session must know. Keep the Commands section in sync.
6. **Commit.** `git status` and review the diff (no `.env`, no weights). Commit with a message naming the session, e.g. `Session 2: frontend workspace`, ending with the attribution trailer.
