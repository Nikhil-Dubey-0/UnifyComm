---
name: run-demo
description: Run the UnifyComm ARCHITECTURE §17 demo end to end on the simulator - reset and seed, start api/worker/web, run the Playwright demo (steps 1-5), the worker stop/restart check (step 6) and the LLM-off check (step 7), and report each step. Use before a demo or when asked to verify the full loop.
---

# Run the demo (ARCHITECTURE §17)

Paths are from the repo root. Windows: Git Bash or PowerShell. Keep logs out of the repo (scratchpad).

1. **Reset and seed** (only before a real demo; the spec itself is re-runnable without it):
   `cd backend; uv run alembic upgrade head; uv run python -m scripts.seed --reset`
2. **Start the stack** (three background processes):
   - `cd backend; uv run uvicorn app.main:app --port 8000`
   - `cd backend; uv run python -m app.worker` (with `AI_MODE=real` the first labels take 30–40 s after start)
   - `cd frontend; npm run dev` (for the audience: `npm run build; npm start`)
   Wait for `GET http://localhost:8000/api/health` to show `db: ok`, a fresh `worker_heartbeat_at` and `llm_configured: true`.
3. **Steps 1–5:** `cd frontend; npx playwright test src/e2e/demo.spec.ts` (set `DEMO_SCREENSHOTS=<dir>` for a screenshot per step). The spec resolves the seeded customers' active conversations and restores §17 preferences first. Step 5 also fails `time.promo_window` after 21:00 IST; the spec allows that.
4. **Step 6 (worker down):** stop the worker; `POST /api/channels/simulator/inbound` (or use the simulator page); `GET /api/conversations/{id}` shows `ai: {intent: null, sentiment: null}` and the UI shows "Analysis pending"; start the worker; labels and the acknowledgement appear (35 s with real models, mostly model loading).
5. **Step 7 (LLM off):** stop the api and start it with the key emptied: Git Bash `OPENAI_API_KEY= uv run uvicorn app.main:app --port 8000`, PowerShell `$env:OPENAI_API_KEY=''; uv run uvicorn app.main:app --port 8000`. `/api/health` shows `llm_configured: false`. Run the spec again: the step 7 test runs and steps 1–5 skip. Restart the api normally afterwards.
6. **Report** each step as pass/fail with the failing assertion. Never loosen an assertion to make the demo pass: a blocked reply usually means the compliance gate did its job (e.g. a 13+ digit number that passes Luhn is treated as a card number).
7. **Stop** the processes. `next dev` survives a stopped `npm run dev`: `taskkill /PID <next dev pid> /T /F`.
