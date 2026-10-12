## Start everything (4 terminals)

PostgreSQL starts with Windows, so no step is needed for it. Open **4 PowerShell windows**:

**Terminal 1: tunnel** (only needed for real WhatsApp; skip it for a simulator-only demo)
```powershell
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8000
```
After a few seconds it prints an address like `https://something-random.trycloudflare.com`. Copy it, then:
1. Open `C:\UnifyComm\.env` and set `PUBLIC_BASE_URL=https://something-random.trycloudflare.com` (no `/` at the end). Save.
2. In Twilio → **Sandbox settings** → **"When a message comes in"**, paste the same address followed by `/api/webhooks/twilio/whatsapp`. Save.

**Terminal 2: API**
```powershell
cd C:\UnifyComm\backend
uv run uvicorn app.main:app --port 8000
```

**Terminal 3: worker** (AI models, sending messages, reading Gmail)
```powershell
cd C:\UnifyComm\backend
uv run python -m app.worker
```
Wait about 40 seconds for the AI models to load.

**Terminal 4: web app**
```powershell
cd C:\UnifyComm\frontend
npm run dev
```
Open http://localhost:3000 and sign in with `agent@unifycomm.local` / `demo1234`.

Start the tunnel **before** the API. The API reads `PUBLIC_BASE_URL` only when it starts, so if you change it later, restart Terminal 2 (Ctrl+C, then run the command again).

## Check that it all works
```powershell
cd C:\UnifyComm\backend
uv run python -m scripts.check_channels
```
Every line should say **ok**, and the tunnel line should show **HTTP 200**. In the app, hover the activity icon at the bottom of the left bar: Worker running, Gmail connected, WhatsApp configured.

## Before presenting to teachers
- Clean the demo data: `cd C:\UnifyComm\backend; uv run python -m scripts.seed --reset`. This wipes all conversations and keeps the demo customers and your own test contact.
- On your phone, send `join <code>` to the Twilio sandbox number again. The join lasts only 72 hours.
- For a faster app during the presentation, use `npm run build` then `npm start` in Terminal 4 instead of `npm run dev`.

## Stop everything
Press **Ctrl+C** in each terminal. If port 3000 is still busy afterwards, close leftover Node processes in Task Manager.

I can also make a `start.ps1` file that opens all four windows with one double-click, if that would help on presentation day.