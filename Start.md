Here's the full sequence, from a fresh start (after a reboot, or on presentation day). Run everything in **PowerShell**.

## 1. Stop anything still running
```powershell
cd C:\UnifyComm
.\stop.ps1
```

## 2. (Optional) Clean the demo data
Do this before showing teachers. It wipes all conversations but keeps the demo customers (Rahul, Priya, Amit) and you as the test contact.
```powershell
cd C:\UnifyComm\backend
uv run python -m scripts.seed --reset
cd C:\UnifyComm
```

## 3. Start everything with one command
```powershell
cd C:\UnifyComm
.\start.ps1
```
This opens 3 windows (**api**, **worker**, **web**), starts the tunnel, updates `.env`, and prints a line like this:
```
Paste this into Twilio > WhatsApp Sandbox settings > 'When a message comes in' (POST):
  https://xxxx-xxxx-xxxx.trycloudflare.com/api/webhooks/twilio/whatsapp
(already copied to the clipboard)
```
Wait about **40 seconds** for the worker to load the AI models.

To start without WhatsApp (simulator and email only), use `.\start.ps1 -NoTunnel` and skip step 5.

## 4. Check that everything works
```powershell
cd C:\UnifyComm\backend
uv run python -m scripts.check_channels
```
You should see:
```
gmail IMAP: ok
gmail SMTP: ok
gmail allowlist: 1 sender(s)
twilio API: ok
tunnel: HTTP 200 ...
```

## 5. Twilio (each time you run `start.ps1`, because the address changes)
1. Open https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn?frameUrl=%2Fconsole%2Fsms%2Fwhatsapp%2Flearn%3Fx-target-region%3Dus1
2. In **"When a message comes in"**, paste the URL from step 3 (it's on your clipboard). Method **POST**. Click **Save**.
3. On your phone, send the **two-word join code** shown on that page (like `join silver-river`) to **+1 415 523 8886**. Only needed once every 72 hours. Use the **two-word** code, not `join twilio-trial`.

## 6. Use the app
- Open **http://localhost:3000**
- Sign in with **agent@unifycomm.local** / **demo1234**
- **WhatsApp test:** send a message to **+1 415 523 8886** from your phone.
- **Email test:** send from **nikhildubey2thousand3@gmail.com** to **nikhil.dubey.2004.oct@gmail.com**.
- **Simulator:** the phone icon in the left bar.

## 7. Stop everything when done
```powershell
cd C:\UnifyComm
.\stop.ps1
```

## If you'd rather do it by hand (4 separate terminals)
```powershell
# Terminal 1: tunnel. Copy the https://...trycloudflare.com address it prints,
# put it in C:\UnifyComm\.env as PUBLIC_BASE_URL=<address>, then start Terminal 2.
& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8000

# Terminal 2: API
cd C:\UnifyComm\backend
uv run uvicorn app.main:app --port 8000

# Terminal 3: worker (AI models, sending, reading Gmail)
cd C:\UnifyComm\backend
uv run python -m app.worker

# Terminal 4: web app
cd C:\UnifyComm\frontend
npm run dev
```

**If Terminal 2 says "only one usage of each socket address"**, an old copy is still running. Run `.\stop.ps1` and start again.