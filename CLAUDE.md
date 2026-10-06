# CLAUDE.md

UnifyComm is an AI-assisted omnichannel customer-support platform (FastAPI + PostgreSQL + Next.js, with the team's intent and sentiment models and OpenAI for drafts and summaries). This is a 3-person B.Tech semester project; build quality matters more than feature count.

**`ARCHITECTURE.md` is the contract.** Read it before changing anything. If a task needs a new or changed table, enum, endpoint, event, job kind or compliance rule, update `ARCHITECTURE.md` first, then the code. `Picture.md`, the report PDF and the PPTX are background only; where they disagree with `ARCHITECTURE.md`, follow `ARCHITECTURE.md`. `SKILLS.md` lists the references to use per area.

## Status

Update this block at the end of every session: tick finished items, note carry-over, record anything the next session must know.

- [x] Session 1: backend foundation and walking skeleton (backend half), done 2026-10-06
- [x] Session 2: frontend workspace, walking skeleton complete, done 2026-10-06
- [ ] Session 3: real models (intent Plan A or B, sentiment)
- [ ] Session 4: OpenAI drafts and summaries, compliance, full demo on simulator
- [ ] Session 5: Gmail + Twilio WhatsApp, metrics, hardening, README

Notes for the next session:
- **Session 2 result (2026-10-06):** all §16 Session 2 items done. Next.js 16.3.8 + React 19.2, Tailwind 4, shadcn/ui (radix base, Nova preset), TanStack Query 5.104, openapi-fetch 0.17 / openapi-typescript 7.13, Playwright 1.63. Exit criteria verified: Playwright smoke passes (login → simulator message → live inbox → reply delivered → visible in simulator), `npm run build`, `tsc --noEmit` and `npm run lint` clean, backend 153 tests green. WebSocket reconnect was verified by stopping and restarting the api with a page open (indicator closed → open).
- Session 2 contract changes (in ARCHITECTURE): `GET /api/agents`; §11 client invalidation also covers `["simulator-thread"]` and `["customer"]`, and close code 1008 logs out. Response models with defaults set `json_schema_serialization_defaults_required=True` so generated TS types are not optional.
- Fixed in Session 2 (test first): the fake classifiers ranked runner-ups above the top label in `top_k`.
- Frontend notes: Playwright uses the installed **Microsoft Edge** (`channel: "msedge"`, override with `PW_CHANNEL`), so no browser download is needed; `playwright.config.ts` reuses running api/worker/web or starts them. Next 16 specifics: read `frontend/node_modules/next/dist/docs/` before using an API (`params` are Promises in server components; client pages use `useParams`; `useSearchParams` needs `<Suspense>`). React 19's lint rule forbids `setState` inside effects: derive state instead. The queue list for filters (`lib/format.ts` `CATEGORY_QUEUES`) mirrors §7.3. The dev indicator sits bottom-right and toasts top-centre so neither covers the nav rail.
- The `frontend-design` skill (SKILLS B2) is not installed here; the design pass was done by hand with screenshot review. Install it before Session 4's UI work if a deeper pass is wanted.
- Dev DB now contains smoke-test senders ("Smoke <timestamp>"); `uv run python -m scripts.seed --reset` before a demo.
- **Session 1 result (2026-10-06):** all §16 Session 1 items done. 149 backend tests green (unit, integration on `unifycomm_test`, import boundary with a positive control); ruff clean; `alembic check` clean. `scripts/check_walking_skeleton.py` passed against live api + worker: fake labels visible 0.48 s after a simulator POST, WS received `message.created` + `message.analyzed`, duplicate external ID returned 200 `duplicate: true`, agent reply delivered to the simulator thread, api imports no torch. Dev DB is migrated and seeded (customers 1 Rahul, 2 Priya, 3 Amit; agents `agent@`/`admin@unifycomm.local`).
- Contract changes made in Session 1 (already in ARCHITECTURE): simulator inbound takes optional `external_id`; `SendResult.delivered`; `messages.metadata` holds `from` (inbound) / `to` (outbound) normalized addresses; D11 text aligned to floor 0.50; `LOG_LEVEL` setting; WS bad token closes with 1008.
- New dependency `tzdata` (user-approved): Windows Python has no timezone database, needed for `ZoneInfo("Asia/Kolkata")`.
- Deliberately left for later sessions per §16: the §7.6 compliance rules (registry `app/compliance/rules.py` is empty = allow-all), `PUT /customers/{id}/preferences`, outreach, `GET /compliance/checks`, drafts/summarize endpoints, `send_acknowledgement` and `summarize_conversation` jobs (no handlers yet; do not enqueue them before adding one), email quote/signature stripping and token truncation in `ai/text_prep.py` (Session 3), `app/ai/local/` real classifiers (worker loads them lazily via `worker/classifiers.py`).
- Session 2 starts from `frontend/openapi.json` (exported, 15 paths). Run `uv run python -m scripts.export_openapi` after any schema change.
- Gotchas: never use reserved LogRecord names (`name`, `message`, `args`, …) as logging `extra` keys; uvicorn logs are filtered to redact `token=`; the full test suite takes ~1.5 min (Argon2 + a fresh DB connection per request under NullPool).
- Project skills created in `.claude/skills/`: `db-migration`, `add-api-endpoint`, `session-wrapup`.
- Environment ready (2026-10-06): PostgreSQL 17.11 service `postgresql-x64-17` running; role `unifycomm`/`unifycomm` owns DBs `unifycomm` and `unifycomm_test`; `postgres` superuser password is `PG_SUPERUSER_PASSWORD` in `.env`. `backend/.venv` created with `uv sync` (torch 2.14.1+cpu, transformers 5.18.0, fastapi 0.142.2, sqlalchemy 2.1.3, asyncpg 0.31, openai 3.24). Git initialized on `main`, nothing committed yet.
- Network re-signs TLS: `backend/pyproject.toml` sets `native-tls = true` for uv. For curl downloads from EnterpriseDB/CloudFront use `curl -4` (IPv6 stalls).
- Network re-signs TLS for Python too: any HTTPS from Python (OpenAI, Hugging Face downloads) needs `truststore.inject_into_ssl()` at process start on this machine. `truststore` is a backend dependency; call it in `app/config.py` setup for both the api and the worker.
- **Intent model ready: `models/intent/repro-v1/`** (retrained in Colab, Plan B; results in ARCHITECTURE §8.2). It verifies offline on CPU with 6/6 golden matches (`ml/intent/verify_export.py`, which is the reference loader for `LocalIntentClassifier`). `.env` points at it; the confidence floor is 0.50 (from `threshold_analysis.json`). The weights file is gitignored. Backups: `models/intent/unifycomm_intent_repro-v1.zip` locally and the teammate's Drive. Built from `ml/intent/retrain_intent.py` → `build_notebook.py` → `unifycomm_intent_retrain.ipynb`.
- The `final_model/` and `banking77_checkpoint/` folders are the teammate's history (no weights). Do not load them.
- `ml/.venv` is a CPU env for dry runs and verification only; real training happens in Colab (T4).
- The two original team notebooks are in the repo root: `notebook1session1Banking77 (2).ipynb` (intent Stage 1) and `sentimnt_notebook (2).ipynb` (sentiment eval, stock cardiffnlp, no fine-tuning).
- Inference must apply the notebook's `clean_text` (lowercase, keep `[a-z0-9\s.,!?'-]`, collapse spaces) before tokenizing (ARCHITECTURE §8.2).
- Sentiment is the public `cardiffnlp/twitter-roberta-base-sentiment-latest`; download it, do not look for local weights.

## Hard rules

1. **Never replace, retrain, fine-tune, quantize or substitute the team's models** without the user's explicit instruction. The only sanctioned retraining is ARCHITECTURE §8.2 Plan B, and only after the user confirms Plan A is unavailable.
2. **The `api` process never imports `torch` or `transformers`.** Torch code lives only in `backend/app/ai/local/` and is imported only by the worker. `tests/test_import_boundary.py` must stay green.
3. **One way in, one way out.** Every inbound message goes through `services/ingest.py`. Every outbound message goes through `services/outbound.py` and the compliance engine. No other code inserts message rows.
4. **Never auto-send LLM output.** The only automatic outbound is the fixed acknowledgement template, and it passes compliance too.
5. **The compliance engine is pure.** `app/compliance/` takes a `SendContext` and returns rule results. No DB access, no network, no clock reads (pass `now` in).
6. **WebSocket events are invalidation hints.** The frontend refetches over REST and never builds state from event payloads.
7. **Idempotency lives in the database** (unique indexes plus `ON CONFLICT`). Never check-then-insert.
8. **Secrets stay in `.env`.** Never print, log or commit `OPENAI_API_KEY`, Twilio or email credentials. Never write real keys into `.env.example`.
9. **No model weights in git.** `*.safetensors`, `*.bin`, `*.pt` and `models/sentiment/hf/` are gitignored.
10. **Do not add infrastructure** (Redis, Kafka, Celery, MongoDB, Kubernetes, LangChain) or a new major dependency without asking.
11. **Don't touch the reference files** (`Picture.md`, the PDF, the PPTX) or the teammate's files in `models/` except to add the missing weights.

## Environment

- Windows 11, PowerShell 5.1 (no `&&`; use `;` or `if ($?) { }`). Git Bash is also available.
- 7.3 GB RAM, Ryzen 5 5600H, GTX 1650 4 GB. **No Docker.** Run everything natively. Do not run model training while the app stack is up.
- Python 3.13 via `uv` (installed). Node 24 + npm (no pnpm). Git 2.51.
- PostgreSQL 17 as a native Windows service on port 5432 (install: `winget install PostgreSQL.PostgreSQL.17`).
- Database driver is **asyncpg** everywhere. psycopg 3 async fails on Windows' Proactor event loop.
- The app venv uses **CPU-only torch**. CUDA torch only in the separate `ml/` env (Plan B).

## Commands

Run from the repo root unless noted. Backend commands run in `backend/`, frontend commands in `frontend/`.

```powershell
# Backend setup
cd backend; uv sync
uv run alembic upgrade head
uv run python -m scripts.seed            # idempotent; --reset truncates all tables first

# Run (three terminals)
cd backend; uv run uvicorn app.main:app --port 8000 --reload
cd backend; uv run python -m app.worker
cd frontend; npm run dev

# Checks
cd backend; uv run pytest                      # all except golden model tests
cd backend; uv run pytest -m models            # golden tests (need weights)
cd backend; uv run ruff check .; uv run ruff format --check .
cd backend; uv run alembic check                # ORM and migrations agree
cd backend; uv run python -m scripts.check_walking_skeleton   # needs api + worker running
cd backend; uv run python -m scripts.export_openapi
cd frontend; npm run gen:api; npx tsc --noEmit; npm run lint; npm run build
cd frontend; npx playwright test               # uses Microsoft Edge; starts or reuses api, worker, web

# Models
cd backend; uv run python -m scripts.download_models   # sentiment, pinned revision
```

Keep this section in sync when commands change.

## Code conventions

### Backend
- Layers: `api/` (routers: parse, auth, call a service, return a schema) → `services/` (business logic, transactions) → `models/` (ORM). Routers contain no business logic or SQL.
- Async everywhere (`AsyncSession`). One transaction per request or job; services take the session as an argument and do not commit on their own unless they own the unit of work.
- Pydantic v2 schemas in `schemas/` for every request and response. Never return ORM objects directly.
- Timestamps: `timestamptz`, UTC, `datetime.now(UTC)`. Convert to `Asia/Kolkata` only for compliance windows and display.
- Errors: raise domain exceptions in services. One exception handler maps them to `{"error": {"code", "message"}}`.
- Notify events through `services/events.py` inside the same transaction as the change.
- Job handlers must be idempotent (a lease can expire and the job runs again).
- Config only through `app/config.py` (`Settings`). No `os.environ` reads elsewhere.
- Prompts live in `backend/config/prompts/*.md`. Intent categories live in `backend/config/intent_map.yaml`.
- Logging: standard `logging` with structured `extra`. No message bodies or secrets above DEBUG.
- Style: ruff (format + lint), type hints on all public functions, small modules, no commented-out code.

### Frontend
- App Router with client components for the workspace (`"use client"`). Data via TanStack Query hooks over the generated `openapi-fetch` client. No hand-written API types; run `npm run gen:api` after backend schema changes.
- Query keys: `["conversations", filters]`, `["conversation", id]`, `["customer", id]`, `["simulator-thread", channel, address]`.
- One socket per session in `lib/ws.ts`; events only call `queryClient.invalidateQueries`.
- Every AI element has three visible states: loading/pending, ok, unavailable.
- Tailwind + shadcn/ui components. Use the `frontend-design` skill for visual work.

### Tests
- Every bug fix gets a test that fails before the fix.
- Integration tests use `TEST_DATABASE_URL` and truncate tables between tests. Never point tests at the dev database.
- Use fake classifiers (`AI_MODE=fake`) in tests except `tests/models/`.
- A worker job can be run synchronously in tests via `worker.loop.process_one_job()`.

## Working method for each session

1. Start: read the Status block and the session's checklist in ARCHITECTURE §16. Run the backend and frontend checks. If anything is red, fix it before new work.
2. Work in vertical slices: schema → service → endpoint → test → UI. Run the relevant tests after each slice.
3. Before claiming something works, run it. Use real commands (pytest, curl/`Invoke-RestMethod`, Playwright), not inference.
4. End: run all checks, run the session's exit criteria, update the Status block, and update ARCHITECTURE.md if any contract changed. If git is initialized, commit with a message that names the session.

## Ask the user before

- Choosing intent Plan B (retraining).
- Adding a dependency that is not in ARCHITECTURE §16 or `SKILLS.md`.
- Changing a decision in ARCHITECTURE §2.
- Anything that sends real messages (Twilio, SMTP) to a real number or address other than the user's own test contacts.
- Spending money: changing the OpenAI model to a more expensive one, buying Twilio numbers.
