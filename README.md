# UnifyComm

AI-assisted omnichannel customer support for banks and other regulated businesses (B.Tech semester project, group G16).

Customer messages arrive by WhatsApp, SMS or email. Each one is matched to a known customer, joined to that customer's open conversation and labelled by the team's intent and sentiment models. Agents work every channel in one live workspace, with AI reply drafts and summaries. A compliance gate checks every outbound message before any provider is called.

```
ingest → identify customer → attach to conversation → intent + sentiment → live workspace
      → AI draft → agent edits → compliance gate → deliver (simulator, Gmail, Twilio WhatsApp)
```

- **Design and contracts:** [`ARCHITECTURE.md`](ARCHITECTURE.md) (tables, endpoints, events, compliance rules, the demo script in §17).
- **How the code was built:** [`CLAUDE.md`](CLAUDE.md) (status, conventions) and [`SKILLS.md`](SKILLS.md).
- **Presenting it:** [`docs/PRESENTATION_GUIDE.md`](docs/PRESENTATION_GUIDE.md) (what to say, demo script, likely questions).

## What it does

| Area | What is real |
|---|---|
| Channels | Customer simulator for WhatsApp, SMS and email; real email through Gmail (IMAP/SMTP); real WhatsApp through the Twilio sandbox |
| Identity | Exact phone (E.164) and email matching. Staff register known customers (Customers → New customer) so their phone and email share one conversation; unknown senders become unverified customers that an agent can link |
| AI analysis | Intent: the team's MiniLM model (213 labels, Banking77 + CLINC150, retrained as `repro-v1`). Sentiment: `cardiffnlp/twitter-roberta-base-sentiment-latest`. Both run locally on CPU in the worker |
| Routing | Category queues, sticky primary intent, priority from category and negative sentiment |
| AI assistance | Reply drafts with "check before sending" hints, and conversation summaries (OpenAI `gpt-6-luna`, PII redacted, never sent automatically) |
| Compliance | 8 rules (consent, opt-in for proactive messages, DND, 09:00–21:00 IST promo window, WhatsApp 24 h window, card/Aadhaar/OTP requests, prohibited claims, length), stored for every message, with a compliance log |
| Workspace | Live inbox (WebSocket), conversation view, customer pages, channel preferences, compliance log, metrics |

## Requirements

- Windows 10/11 (developed natively; Docker is not used).
- [PostgreSQL 17](https://www.postgresql.org/download/windows/): `winget install PostgreSQL.PostgreSQL.17`
- Python 3.13 through [uv](https://docs.astral.sh/uv/): `winget install astral-sh.uv`
- Node.js 24 with npm.
- Microsoft Edge (Playwright tests use the installed Edge).
- About 3 GB of free RAM while everything runs: the worker holds both models (about 0.7 GB).

Optional: an OpenAI API key (drafts and summaries), a Gmail account with an app password (real email), a Twilio account plus `cloudflared` (real WhatsApp).

## Setup

All commands are PowerShell, from the repository root.

**1. Database.** Create the role and the two databases. `psql` lives in `C:\Program Files\PostgreSQL\17\bin`; it asks for the `postgres` password you chose when installing:

```powershell
psql -U postgres -c "CREATE ROLE unifycomm LOGIN PASSWORD 'unifycomm';"
psql -U postgres -c "CREATE DATABASE unifycomm OWNER unifycomm;"
psql -U postgres -c "CREATE DATABASE unifycomm_test OWNER unifycomm;"
```

**2. Configuration.** Copy the template and fill it in. Every setting is described in ARCHITECTURE §13.

```powershell
Copy-Item .env.example .env
```

At minimum set `JWT_SECRET` to a long random string (`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Leave `AI_MODE=fake` until the models are in place. `.env` is never committed.

**3. Backend.**

```powershell
cd backend
uv sync                                  # Python packages, CPU-only torch
uv run alembic upgrade head              # create the tables
uv run python -m scripts.seed            # demo customers and agents (--reset wipes everything first)
```

**4. Models** (for `AI_MODE=real`):

- **Sentiment.** Run `uv run python -m scripts.download_models`. It downloads the pinned revision into `models/sentiment/hf/` and checks its sha256.
- **Intent.** Unzip `unifycomm_intent_repro-v1.zip` (from the team's Google Drive, `MyDrive/UnifyComm/models/intent/`) into `models/intent/repro-v1/`.
- **Check.** `uv run pytest -m models` runs the golden tests from ARCHITECTURE §8.5.

Weights are never committed.

**5. Frontend.**

```powershell
cd frontend
npm install
```

## Run

**One command** (from the repository root, in PowerShell):

```powershell
.\start.ps1             # tunnel + api + worker + web, each in its own window
.\start.ps1 -NoTunnel   # without the tunnel (simulator and email only)
.\stop.ps1              # stop everything
```

`start.ps1` writes the new tunnel address into `.env` (`PUBLIC_BASE_URL`) and copies the Twilio webhook URL to the clipboard; paste it into the Sandbox settings (see Real channels). It refuses to start while ports 8000 or 3000 are in use, so run `.\stop.ps1` first if anything is left over.

Or by hand, in three terminals:

```powershell
cd backend; uv run uvicorn app.main:app --port 8000      # api
cd backend; uv run python -m app.worker                  # worker: models, jobs, email poller
cd frontend; npm run dev                                 # web app on http://localhost:3000
```

**Simulated or real.** Every message shows which provider carried it: `simulated` (the customer simulator), `via Twilio` (real WhatsApp) or `via Gmail` (real email). The inbox sorts by **Newest** or by **Most urgent** (urgent first, then the longest-waiting customer).

Sign in at http://localhost:3000 as `agent@unifycomm.local` with the password `SEED_AGENT_PASSWORD` (default `demo1234`). For a presentation, use `npm run build; npm start` instead of `npm run dev`: it is faster and uses far less memory.

With real models the worker needs 30–40 s after start before the first labels appear. The activity icon at the bottom of the left bar shows the worker, the AI assistant and each channel.

## Demo

The demo script is ARCHITECTURE §17. Open the **Customer simulator** (phone icon) next to the **Inbox** and follow the table, or run it automatically:

```powershell
cd backend; uv run python -m scripts.seed --reset        # clean data before an audience
cd frontend; npx playwright test src/e2e/demo.spec.ts    # steps 1–5 (needs the OpenAI key)
```

Steps 6 (worker stopped) and 7 (no OpenAI key) are described in `.claude/skills/run-demo/SKILL.md`.

## Real channels

The app only replies through the provider that carried the customer's message. A simulator conversation never reaches a real phone, and simulated customers never get a real email.

Check your settings at any time without sending anything:

```powershell
cd backend; uv run python -m scripts.check_channels
```

### Gmail

1. Use a personal Gmail account (college accounts often block app passwords). Turn on 2-Step Verification, then create an app password at https://myaccount.google.com/apppasswords.
2. In `.env` set `EMAIL_ADDRESS`, `EMAIL_APP_PASSWORD` (the 16 letters) and `EMAIL_ALLOWED_SENDERS`, the addresses allowed to write in.
   - **Why the allowlist:** this is a real inbox and every new conversation gets an automatic acknowledgement, so only allowlisted senders are read.
   - **Empty means nobody:** with `EMAIL_ALLOWED_SENDERS` empty, no email is read at all.
3. Restart the worker. It polls the inbox every 20 s.

**Avast antivirus:** Mail Shield re-signs mail connections with a certificate Windows does not trust, and the app never skips certificate checks. If `check_channels` reports `SSLCertVerificationError` for IMAP, turn off *Avast → Settings → Protection → Core Shields → Mail Shield → Scan SSL connections*.

### WhatsApp (Twilio sandbox)

1. In the Twilio console copy the **Account SID** and **Auth Token** into `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`.
2. Open **Messaging → Try it out → Send a WhatsApp message** (or https://console.twilio.com/us1/develop/sms/settings/whatsapp-sandbox). From your phone, send the two-word `join <code>` text shown there to **+1 415 523 8886**. The join lasts 3 days.
   - **Not** the "WhatsApp Tryout" number that answers `join twilio-trial` ("Standard auto-reply… Tryout UI"). That trial sender rejects free-text messages through the API (Twilio 21654, ContentSid Required), so agent replies cannot be delivered from it.
3. Start everything with `.\start.ps1`. It starts a cloudflared tunnel (install it with `winget install --id Cloudflare.cloudflared --source winget`), writes the `https://….trycloudflare.com` address into `PUBLIC_BASE_URL`, and copies the webhook URL to the clipboard. Webhook signatures are checked against `PUBLIC_BASE_URL`.
4. (By hand instead: `cloudflared tunnel --url http://localhost:8000`, put the address in `PUBLIC_BASE_URL` without a trailing slash, then start the api.)
5. In the sandbox settings set **When a message comes in** to `https://….trycloudflare.com/api/webhooks/twilio/whatsapp` (method POST). Delivery receipts use `/api/webhooks/twilio/status` automatically.

The tunnel address changes every time cloudflared starts: repeat steps 4 and 5. The sandbox only reaches phones that joined. Outside 24 h after the customer's last message WhatsApp needs approved templates, so the app blocks those replies itself (`whatsapp.session_window`).

### One person on both channels

Identity matching is exact, so a phone number and an email address only meet in one conversation if they belong to the same customer. Put your own details in `TEST_CONTACT_NAME`, `TEST_CONTACT_PHONE` and `TEST_CONTACT_EMAIL` and run `uv run python -m scripts.seed`. A WhatsApp message and a follow-up email from you then land in the same conversation.

## Tests and checks

```powershell
cd backend
uv run pytest                    # unit + integration on unifycomm_test (about 6 min)
uv run pytest -m models          # golden model tests (need the weights)
uv run ruff check .; uv run ruff format --check .
uv run alembic check             # ORM and migrations agree

cd frontend
npm run gen:api; npx tsc --noEmit; npm run lint; npm run build
npx playwright test              # smoke + demo; starts or reuses api, worker and web
```

Tests never touch the dev database or a real channel, and never call OpenAI.

Useful scripts (in `backend/`):

| Command | What it does |
|---|---|
| `scripts.check_llm` | Real OpenAI drafts and a summary on fixed cases, for reviewing prompt changes (costs cents) |
| `scripts.check_real_models` | Label latency with the real models (api + worker running) |
| `scripts.load_test_data load` / `spread` / `measure` / `purge` | Synthetic traffic on the simulator, backdated for the charts, endpoint timings, and removing it again |
| `scripts.export_openapi` | Writes `frontend/openapi.json`; then `npm run gen:api` in `frontend/` |

## Measured on the development laptop

Ryzen 5 5600H, 7.3 GB RAM, CPU inference:

- Labels visible 0.7 s after a message. Intent model 50 ms, sentiment 113 ms (median).
- AI drafts 4–8 s, summaries 3.5 s.
- Ingest about 20 ms per message. With 215 conversations, every read endpoint answers in under 70 ms at p95.

## Repository layout

```
backend/   FastAPI api + worker (app/), Alembic migrations, config (intent map, prompts), scripts, tests
frontend/  Next.js 16 workspace (src/app, src/components, src/lib), Playwright tests (src/e2e)
models/    model metadata (weights are downloaded or unzipped locally, never committed)
ml/        the retraining pipeline for the intent model (Colab notebook, verification)
```

## Credits and licences

- **Intent model.** Encoder [`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) (Apache-2.0). Fine-tuned by the team on [Banking77](https://huggingface.co/datasets/legacy-datasets/banking77) (Casanueva et al., 2020, CC BY 4.0) and [CLINC150](https://huggingface.co/datasets/clinc/clinc_oos) (Larson et al., 2019, CC BY 3.0).
- **Sentiment model.** [`cardiffnlp/twitter-roberta-base-sentiment-latest`](https://huggingface.co/cardiffnlp/twitter-roberta-base-sentiment-latest) (Loureiro et al., 2022, *TimeLMs*), used as published without fine-tuning, CC BY 4.0.
- **Drafts and summaries.** The OpenAI API (Responses API, `store=False`); customer data is redacted before it is sent.
- **Software.** FastAPI, SQLAlchemy, Alembic, Pydantic, PyTorch, Hugging Face Transformers, Next.js, React, Tailwind CSS, shadcn/ui, TanStack Query, Playwright and the other packages in `backend/pyproject.toml` and `frontend/package.json`, under their own licences.
- **Known limitations and corrections to the original report:** ARCHITECTURE §18.
