"""Check the real channel settings in .env without sending anything (ARCHITECTURE §9.2).

- Gmail: IMAP login + INBOX select, SMTP STARTTLS login. Reads no mail, sends nothing.
- Twilio: GET the account resource with the SID and token. Sends nothing.
- Tunnel: GET PUBLIC_BASE_URL/api/health through the tunnel (needs the api running).
Prints only outcomes and error types, never credentials.

uv run python -m scripts.check_channels
"""

import asyncio
import imaplib
import re
import smtplib
import ssl

import httpx

from app.config import Settings, get_settings, setup_process


def check_gmail(s: Settings) -> list[str]:
    if not s.email_configured:
        return ["gmail: not configured (EMAIL_ADDRESS / EMAIL_APP_PASSWORD empty)"]
    lines = []
    if not re.fullmatch(r"[a-z]{16}", s.email_password):
        lines.append(
            "gmail: EMAIL_APP_PASSWORD does not look like an app password (16 letters). "
            "Create one at https://myaccount.google.com/apppasswords (needs 2-Step Verification)."
        )
    try:
        imap = imaplib.IMAP4_SSL(
            s.imap_host, 993, ssl_context=ssl.create_default_context(), timeout=20
        )
        imap.login(s.email_address, s.email_password)
        imap.select("INBOX", readonly=True)
        imap.logout()
        lines.append("gmail IMAP: ok (login and INBOX)")
    except imaplib.IMAP4.error as exc:
        hint = "app password required" if b"Application-specific" in str(exc).encode() else ""
        lines.append(f"gmail IMAP: login rejected {hint}".rstrip())
    except (OSError, ssl.SSLError) as exc:
        lines.append(f"gmail IMAP: {type(exc).__name__}")
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(s.email_address, s.email_password)
        lines.append(f"gmail SMTP: ok (STARTTLS on {s.smtp_port}, login only)")
    except smtplib.SMTPAuthenticationError:
        lines.append("gmail SMTP: login rejected")
    except (smtplib.SMTPException, OSError) as exc:
        lines.append(f"gmail SMTP: {type(exc).__name__}")
    allowed = s.allowed_email_senders
    lines.append(
        "gmail allowlist: "
        + ("EMPTY, no email will be ingested" if not allowed else f"{len(allowed)} sender(s)")
    )
    return lines


async def check_twilio(s: Settings) -> list[str]:
    if not s.twilio_send_configured:
        return ["twilio: not configured (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN empty)"]
    lines = []
    url = f"https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}.json"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                url, auth=(s.twilio_account_sid, s.twilio_auth_token.get_secret_value())
            )
        if r.is_success:
            body = r.json()
            lines.append(f"twilio API: ok (account {body.get('status')}, type {body.get('type')})")
        else:
            lines.append(f"twilio API: HTTP {r.status_code} (check SID and auth token)")
    except httpx.HTTPError as exc:
        lines.append(f"twilio API: {type(exc).__name__}")
    if not s.public_base_url:
        lines.append("tunnel: PUBLIC_BASE_URL empty (webhooks cannot reach this laptop)")
        return lines
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(s.public_base_url.rstrip("/") + "/api/health")
        lines.append(f"tunnel: HTTP {r.status_code} from {s.public_base_url}/api/health")
    except httpx.HTTPError as exc:
        lines.append(f"tunnel: {type(exc).__name__} (is cloudflared and the api running?)")
    return lines


async def main() -> None:
    settings = get_settings()
    setup_process(settings)
    for line in [*await asyncio.to_thread(check_gmail, settings), *await check_twilio(settings)]:
        print(line)


if __name__ == "__main__":
    asyncio.run(main())
