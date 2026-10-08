"""Gmail IMAP poller (ARCHITECTURE §9.2.1). Runs in the worker every EMAIL_POLL_SECONDS.

Only allowlisted senders are ingested; everything else is left unread. Messages are
fetched with BODY.PEEK[] and marked \\Seen only after ingest has committed, so a crash
re-ingests at most a duplicate that ingest ignores. A message that cannot be parsed is
marked seen and logged, so it never blocks the ones after it. Skipped (left unread) UIDs
are remembered for the worker's lifetime and not downloaded again.
"""

import asyncio
import imaplib
import logging
import ssl
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Protocol

from app.channels.gmail import Skip, parse_email
from app.config import Settings
from app.errors import DomainError
from app.services import ingest, system
from app.worker.handlers import WorkerContext

log = logging.getLogger(__name__)

STATUS_KEY = system.CHANNEL_KEY_PREFIX + "gmail"
IMAP_TIMEOUT_SECONDS = 30


class Mailbox(Protocol):
    """The IMAP operations the poller needs (sync; called in a worker thread)."""

    def open(self) -> str: ...  # returns UIDVALIDITY
    def search(self, sender: str | None, since: date) -> list[str]: ...
    def fetch(self, uid: str) -> bytes: ...
    def mark_seen(self, uid: str) -> None: ...
    def close(self) -> None: ...


class ImapMailbox:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._imap: imaplib.IMAP4_SSL | None = None

    def open(self) -> str:
        s = self._settings
        self._imap = imaplib.IMAP4_SSL(
            s.imap_host, 993, ssl_context=ssl.create_default_context(), timeout=IMAP_TIMEOUT_SECONDS
        )
        self._imap.login(s.email_address, s.email_password)
        self._imap.select("INBOX")
        _, data = self._imap.response("UIDVALIDITY")
        return (data[0] or b"0").decode() if data else "0"

    def search(self, sender: str | None, since: date) -> list[str]:
        assert self._imap is not None
        criteria = ["UNSEEN", "SINCE", since.strftime("%d-%b-%Y")]
        if sender is not None:
            criteria += ["FROM", f'"{sender}"']
        _, data = self._imap.uid("SEARCH", None, *criteria)
        return [u.decode() for u in (data[0] or b"").split()]

    def fetch(self, uid: str) -> bytes:
        assert self._imap is not None
        _, data = self._imap.uid("FETCH", uid, "(BODY.PEEK[])")
        for item in data:
            if isinstance(item, tuple):
                return item[1]
        raise RuntimeError(f"IMAP FETCH returned no body for UID {uid}")

    def mark_seen(self, uid: str) -> None:
        assert self._imap is not None
        self._imap.uid("STORE", uid, "+FLAGS", "(\\Seen)")

    def close(self) -> None:
        if self._imap is not None:
            try:
                self._imap.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
            self._imap = None


async def poll_once(
    ctx: WorkerContext,
    *,
    since: date,
    mailbox_factory: Callable[[Settings], Mailbox] = ImapMailbox,
    skipped: set[tuple[str, str]] | None = None,
) -> int:
    """One poll. Returns how many messages were ingested (duplicates included).
    `skipped` holds (UIDVALIDITY, UID) pairs left unread by earlier polls."""
    settings = ctx.settings
    skipped = skipped if skipped is not None else set()
    allowed = settings.allowed_email_senders
    mailbox = mailbox_factory(settings)
    ingested = 0
    try:
        uidvalidity = await asyncio.to_thread(mailbox.open)
        senders: list[str | None] = [None] if "*" in allowed else list(allowed)
        uids: list[str] = []
        for sender in senders:
            for uid in await asyncio.to_thread(mailbox.search, sender, since):
                if uid not in uids and (uidvalidity, uid) not in skipped:
                    uids.append(uid)
        for uid in uids:
            raw = await asyncio.to_thread(mailbox.fetch, uid)
            try:
                parsed = parse_email(
                    raw,
                    own_address=settings.email_address,
                    allowed=allowed,
                    fallback_id=f"gmail-{uidvalidity}-{uid}",
                )
            except Exception as exc:
                log.warning(
                    "email could not be parsed; marked read and skipped",
                    extra={"uid": uid, "error": type(exc).__name__},
                )
                await asyncio.to_thread(mailbox.mark_seen, uid)
                continue
            if isinstance(parsed, Skip):
                log.info("email skipped", extra={"uid": uid, "reason": parsed.reason})
                skipped.add((uidvalidity, uid))
                continue
            try:
                async with ctx.sessionmaker() as session:
                    await ingest.ingest(session, parsed, settings)
                ingested += 1
            except DomainError as exc:
                # e.g. an address identity.normalize rejects: do not retry it forever.
                log.warning("email not ingested", extra={"uid": uid, "error": exc.code})
            await asyncio.to_thread(mailbox.mark_seen, uid)
    finally:
        await asyncio.to_thread(mailbox.close)
    return ingested


async def _write_status(ctx: WorkerContext, value: dict) -> None:
    async with ctx.sessionmaker() as session:
        await system.put_status(session, STATUS_KEY, value)
        await session.commit()


async def poll_and_report(
    ctx: WorkerContext,
    *,
    since: date,
    mailbox_factory: Callable[[Settings], Mailbox] = ImapMailbox,
    skipped: set[tuple[str, str]] | None = None,
) -> None:
    """poll_once plus channel health in system_status (error type only, never details
    that could contain addresses or credentials). Never raises: the poller must outlive a
    database or network failure."""
    now = datetime.now(UTC).isoformat()
    try:
        count = await poll_once(ctx, since=since, mailbox_factory=mailbox_factory, skipped=skipped)
        value: dict = {"status": "ok", "at": now, "ingested": count}
        if not ctx.settings.allowed_email_senders:
            value["note"] = "EMAIL_ALLOWED_SENDERS is empty: no email is ingested"
    except Exception as exc:
        log.warning("email poll failed", extra={"error": type(exc).__name__})
        value = {"status": "error", "at": now, "error": type(exc).__name__}
    try:
        await _write_status(ctx, value)
    except Exception as exc:
        log.warning("email status not written", extra={"error": type(exc).__name__})


async def poll_forever(ctx: WorkerContext) -> None:
    """Ignores mail that arrived before the worker's start day (old unread mail)."""
    since = datetime.now(UTC).date()
    skipped: set[tuple[str, str]] = set()
    log.info("email poller started", extra={"every_s": ctx.settings.email_poll_seconds})
    while True:
        try:
            await poll_and_report(ctx, since=since, skipped=skipped)
        except Exception:
            log.exception("email poller error")
        await asyncio.sleep(ctx.settings.email_poll_seconds)
