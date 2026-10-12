"""Real channels against the test database (ARCHITECTURE §9.2.1, §9.2.2): Twilio webhooks
and status callbacks, the Gmail poller, email threading, and the Session 5 exit scenario.
Providers are faked at the network edge (httpx.MockTransport, a fake mailbox, a fake SMTP).
"""

import asyncio
from datetime import date

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text

from app.channels.gmail import GmailAdapter
from app.channels.registry import AdapterRegistry
from app.channels.simulator import SimulatorAdapter
from app.channels.twilio_whatsapp import TwilioWhatsAppAdapter, compute_signature
from app.models import Conversation, Customer, CustomerContact, Message, SystemStatus
from app.worker import email_poller
from scripts.seed import seed, test_contact
from tests.integration.helpers import TEST_PASSWORD, run_all_jobs
from tests.unit.test_gmail import FakeSMTP

BASE = "https://unit-test.trycloudflare.com"
TOKEN = "twilio-test-token"
OWN = "support.unifycomm@gmail.com"
PHONE = "+91 98111 22334"
WA_FROM = "whatsapp:+919811122334"
EMAIL = "nikhil.tester@gmail.com"

TWILIO = {
    "twilio_account_sid": "AC123",
    "twilio_auth_token": SecretStr(TOKEN),
    "public_base_url": BASE,
}
GMAIL = {
    "email_address": OWN,
    "email_app_password": SecretStr("abcd efgh ijkl mnop"),
    "email_allowed_senders": EMAIL,
}


@pytest.fixture
def sent_to_twilio() -> list[dict]:
    return []


@pytest.fixture
def channels(app, worker, settings, sent_to_twilio, monkeypatch):
    """Configure Twilio and Gmail on the app and the worker; fake their network edges."""
    configured = settings.model_copy(update={**TWILIO, **GMAIL})
    app.state.settings = configured
    worker.settings = configured

    def twilio_api(request: httpx.Request) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode()))
        sent_to_twilio.append(form)
        return httpx.Response(201, json={"sid": f"SMout{len(sent_to_twilio)}"})

    monkeypatch.setattr("app.channels.gmail.smtplib.SMTP", FakeSMTP)
    FakeSMTP.sent, FakeSMTP.fail = [], None
    worker.registry = AdapterRegistry(
        [
            SimulatorAdapter(),
            TwilioWhatsAppAdapter(configured, transport=httpx.MockTransport(twilio_api)),
            GmailAdapter(configured),
        ]
    )
    return configured


def twilio_post(client, path: str, form: dict, *, token: str = TOKEN, signature: str | None = ""):
    url = BASE + path
    sig = compute_signature(url, form, token) if signature == "" else signature
    headers = {"X-Twilio-Signature": sig} if sig is not None else {}
    return client.post(path, data=form, headers=headers)


def wa_form(sid: str, body: str, sender: str = WA_FROM) -> dict:
    return {
        "MessageSid": sid,
        "From": sender,
        "To": "whatsapp:+14155238886",
        "Body": body,
        "NumMedia": "0",
        "ProfileName": "Nikhil",
    }


def status_form(sid: str, status: str, error_code: str | None = None) -> dict:
    form = {"MessageSid": sid, "MessageStatus": status}
    if error_code:
        form["ErrorCode"] = error_code
    return form


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


# --- Twilio ----------------------------------------------------------------------------


async def test_whatsapp_webhook_ingests_once(client, db, channels):
    r = await twilio_post(client, "/api/webhooks/twilio/whatsapp", wa_form("SMin1", "Hi there"))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/xml")
    assert r.text.endswith("<Response/>")

    again = await twilio_post(client, "/api/webhooks/twilio/whatsapp", wa_form("SMin1", "Hi there"))
    assert again.status_code == 200
    [msg] = list(await db.scalars(select(Message)))
    assert (msg.provider, msg.channel, msg.external_message_id) == ("twilio", "whatsapp", "SMin1")
    assert msg.meta["from"] == "+919811122334" and msg.meta["sender_name"] == "Nikhil"
    customer = await db.get(Customer, (await db.get(Conversation, msg.conversation_id)).customer_id)
    assert (customer.display_name, customer.verified) == ("Nikhil", False)


@pytest.mark.parametrize(
    "kwargs",
    [{"signature": "bm90LXZhbGlk"}, {"signature": None}, {"token": "someone-elses-token"}],
)
async def test_webhook_rejects_bad_signatures(client, db, channels, kwargs):
    r = await twilio_post(client, "/api/webhooks/twilio/whatsapp", wa_form("SMx", "hi"), **kwargs)
    assert r.status_code == 403 and r.json()["error"]["code"] == "invalid_signature"
    assert await count(db, Message) == 0


async def test_webhook_rejected_when_twilio_is_not_configured(client, db, app, settings):
    app.state.settings = settings  # no token, no public URL
    r = await twilio_post(client, "/api/webhooks/twilio/whatsapp", wa_form("SMy", "hi"))
    assert r.status_code == 403
    r = await twilio_post(client, "/api/webhooks/twilio/status", status_form("SMy", "sent"))
    assert r.status_code == 403


async def test_reply_goes_out_through_twilio_and_status_moves_forward_only(
    client, db, worker, channels, auth_headers, sent_to_twilio
):
    inbound = await twilio_post(client, "/api/webhooks/twilio/whatsapp", wa_form("SMin2", "help"))
    assert inbound.status_code == 200
    await run_all_jobs(worker)  # analysis + the acknowledgement, delivered through Twilio
    conversation_id = await db.scalar(select(Message.conversation_id))

    sent = await client.post(
        f"/api/conversations/{conversation_id}/send",
        json={"channel": "whatsapp", "body": "We are on it."},
        headers={**auth_headers, "Idempotency-Key": "key-twilio-0001"},
    )
    message = sent.json()["message"]
    assert (message["provider"], message["delivery_status"]) == ("twilio", "queued")
    await run_all_jobs(worker)

    assert [f["Body"] for f in sent_to_twilio][-1] == "We are on it."
    assert sent_to_twilio[-1]["To"] == WA_FROM
    assert sent_to_twilio[-1]["StatusCallback"] == BASE + "/api/webhooks/twilio/status"
    reply = await db.get(Message, message["id"])
    await db.refresh(reply)
    assert (reply.delivery_status, reply.external_message_id) == ("sent", "SMout2")

    async def status_of() -> tuple:
        await db.refresh(reply)
        return reply.delivery_status, reply.delivery_error

    status_path = "/api/webhooks/twilio/status"
    assert (
        await twilio_post(client, status_path, status_form("SMout2", "delivered"))
    ).status_code == 200
    assert await status_of() == ("delivered", None)
    # Out-of-order and late callbacks never move it back.
    await twilio_post(client, status_path, status_form("SMout2", "sent"))
    await twilio_post(client, status_path, status_form("SMout2", "failed", "30008"))
    assert await status_of() == ("delivered", None)
    # Unknown SIDs and statuses we do not track are accepted and ignored.
    assert (
        await twilio_post(client, status_path, status_form("SMnope", "read"))
    ).status_code == 200
    assert (
        await twilio_post(client, status_path, status_form("SMout2", "queued"))
    ).status_code == 200


async def test_failed_status_callback_marks_the_message_failed(
    client, db, worker, channels, auth_headers
):
    await twilio_post(client, "/api/webhooks/twilio/whatsapp", wa_form("SMin3", "hello"))
    await run_all_jobs(worker)
    ack = await db.scalar(select(Message).where(Message.is_template.is_(True)))
    assert ack.provider == "twilio" and ack.delivery_status == "sent"
    r = await twilio_post(
        client,
        "/api/webhooks/twilio/status",
        status_form(ack.external_message_id, "undelivered", "63016"),
    )
    assert r.status_code == 200
    await db.refresh(ack)
    assert (ack.delivery_status, ack.delivery_error) == ("failed", "Twilio 63016")
    # The retry button resends a failed message through the same provider.
    retry = await client.post(f"/api/messages/{ack.id}/retry", headers=auth_headers)
    assert retry.status_code == 202


# --- Gmail -----------------------------------------------------------------------------


class FakeMailbox:
    """In-memory IMAP mailbox. `messages` maps UID → raw bytes."""

    def __init__(self, messages: dict[str, bytes], *, fail_open: bool = False):
        self.messages = messages
        self.seen: set[str] = set()
        self.fail_open = fail_open
        self.searches: list = []
        self.closed = False

    def __call__(self, settings):  # used as the mailbox factory
        return self

    def open(self) -> str:
        if self.fail_open:
            raise OSError("IMAP unreachable")
        return "42"

    def search(self, sender, since):
        self.searches.append(sender)
        return [
            uid
            for uid, raw in self.messages.items()
            if uid not in self.seen and (sender is None or sender.encode() in raw.lower())
        ]

    def fetch(self, uid):
        return self.messages[uid]

    def mark_seen(self, uid):
        self.seen.add(uid)

    def close(self):
        self.closed = True


def raw_email(sender: str, subject: str, body: str, message_id: str, extra: str = "") -> bytes:
    return (
        f"From: Nikhil <{sender}>\nTo: {OWN}\nSubject: {subject}\n"
        f"Message-ID: {message_id}\n{extra}\n{body}\n"
    ).encode()


async def test_poller_ingests_allowlisted_mail_and_marks_it_seen(db, worker, channels):
    box = FakeMailbox(
        {
            "1": raw_email(EMAIL, "Card not received", "My card has not arrived.", "<m1@gmail>"),
            "2": raw_email("stranger@example.com", "Hi", "Buy now", "<m2@x>"),
            "3": raw_email(
                EMAIL, "Out of office", "Away", "<m3@gmail>", "Auto-Submitted: auto-replied\n"
            ),
        }
    )
    count_ = await email_poller.poll_once(worker, since=date(2026, 10, 8), mailbox_factory=box)
    assert count_ == 1
    assert box.searches == [EMAIL]  # only allowlisted senders are searched
    assert box.seen == {"1"}  # skipped mail stays unread in the user's inbox
    assert box.closed
    [msg] = list(await db.scalars(select(Message)))
    assert (msg.provider, msg.channel, msg.external_message_id) == ("gmail", "email", "<m1@gmail>")
    assert msg.meta["subject"] == "Card not received" and msg.meta["from"] == EMAIL


async def test_poller_crash_before_mark_seen_only_duplicates(db, worker, channels):
    box = FakeMailbox({"1": raw_email(EMAIL, "Refund", "Refund please", "<dup@gmail>")})
    box.mark_seen = lambda uid: None  # the "crash": nothing is ever marked read
    for _ in range(2):
        await email_poller.poll_once(worker, since=date(2026, 10, 8), mailbox_factory=box)
    await run_all_jobs(worker)
    inbound = select(func.count()).select_from(Message).where(Message.direction == "inbound")
    assert await db.scalar(inbound) == 1
    acks = select(func.count()).select_from(Message).where(Message.is_template.is_(True))
    assert await db.scalar(acks) == 1


async def test_empty_allowlist_ingests_nothing(db, worker, channels):
    worker.settings = worker.settings.model_copy(update={"email_allowed_senders": ""})
    box = FakeMailbox({"1": raw_email(EMAIL, "Hi", "Hello", "<e@gmail>")})
    assert await email_poller.poll_once(worker, since=date(2026, 10, 8), mailbox_factory=box) == 0
    assert box.searches == [] and box.seen == set()


async def test_poll_status_is_reported_in_health(client, db, worker, channels):
    health = (await client.get("/api/health")).json()
    assert health["channels"] == {"simulator": "ok", "gmail": "starting", "twilio": "configured"}

    await email_poller.poll_and_report(
        worker, since=date(2026, 10, 8), mailbox_factory=FakeMailbox({}, fail_open=True)
    )
    row = await db.get(SystemStatus, "channel.gmail")
    assert row.value["status"] == "error" and row.value["error"] == "OSError"
    assert (await client.get("/api/health")).json()["channels"]["gmail"] == "error"

    await email_poller.poll_and_report(
        worker, since=date(2026, 10, 8), mailbox_factory=FakeMailbox({})
    )
    assert (await client.get("/api/health")).json()["channels"]["gmail"] == "ok"


async def test_health_without_real_channels(client, app, settings):
    app.state.settings = settings
    assert (await client.get("/api/health")).json()["channels"] == {
        "simulator": "ok",
        "gmail": "disabled",
        "twilio": "not_configured",
    }
    app.state.settings = settings.model_copy(
        update={"twilio_account_sid": "AC1", "twilio_auth_token": SecretStr("t")}
    )
    assert (await client.get("/api/health")).json()["channels"]["twilio"] == "no_public_url"


async def test_email_reply_is_threaded_and_sent_by_smtp(client, db, worker, channels, auth_headers):
    box = FakeMailbox({"1": raw_email(EMAIL, "Card not received", "Where is it?", "<q1@gmail>")})
    await email_poller.poll_once(worker, since=date(2026, 10, 8), mailbox_factory=box)
    await run_all_jobs(worker)  # analysis + acknowledgement by email
    conversation_id = await db.scalar(select(Message.conversation_id))

    r = await client.post(
        f"/api/conversations/{conversation_id}/send",
        json={"channel": "email", "body": "We are checking the dispatch."},
        headers={**auth_headers, "Idempotency-Key": "key-email-thread"},
    )
    meta = r.json()["message"]["metadata"]
    assert meta["subject"] == "Re: Card not received"
    assert (meta["in_reply_to"], meta["references"]) == ("<q1@gmail>", ["<q1@gmail>"])
    assert r.json()["message"]["provider"] == "gmail"
    await run_all_jobs(worker)

    ack_mime, reply_mime = FakeSMTP.sent
    assert ack_mime["Auto-Submitted"] == "auto-replied"
    assert ack_mime["In-Reply-To"] == "<q1@gmail>"  # the template threads too
    assert reply_mime["Subject"] == "Re: Card not received"
    assert reply_mime["In-Reply-To"] == "<q1@gmail>" and reply_mime["To"] == EMAIL
    reply = await db.get(Message, r.json()["message"]["id"])
    await db.refresh(reply)
    assert (reply.delivery_status, reply.external_message_id) == ("sent", reply_mime["Message-ID"])


# --- Session 5 exit scenario -----------------------------------------------------------


async def test_whatsapp_then_email_from_the_test_contact_share_one_conversation(
    client, db, worker, channels, settings
):
    contact = test_contact(
        settings.model_copy(
            update={
                "test_contact_name": "Nikhil (test)",
                "test_contact_phone": PHONE,
                "test_contact_email": EMAIL,
            }
        )
    )
    await seed(db, TEST_PASSWORD, [contact])
    await db.commit()

    wa = await twilio_post(
        client, "/api/webhooks/twilio/whatsapp", wa_form("SMexit", "My payment failed")
    )
    assert wa.status_code == 200
    await run_all_jobs(worker)
    box = FakeMailbox({"9": raw_email(EMAIL, "Payment", "Any update?", "<exit@gmail>")})
    await email_poller.poll_once(worker, since=date(2026, 10, 8), mailbox_factory=box)
    await run_all_jobs(worker)

    inbound = list(
        await db.scalars(select(Message).where(Message.direction == "inbound").order_by(Message.id))
    )
    assert [(m.provider, m.channel) for m in inbound] == [
        ("twilio", "whatsapp"),
        ("gmail", "email"),
    ]
    assert inbound[0].conversation_id == inbound[1].conversation_id
    conversation = await db.get(Conversation, inbound[0].conversation_id)
    customer = await db.get(Customer, conversation.customer_id)
    assert (customer.display_name, customer.verified) == ("Nikhil (test)", True)
    # One acknowledgement for the one conversation, on the first message's channel.
    acks = list(await db.scalars(select(Message).where(Message.is_template.is_(True))))
    assert [(a.provider, a.channel) for a in acks] == [("twilio", "whatsapp")]


# --- code-review fixes (Session 5) -----------------------------------------------------


class CountingMailbox(FakeMailbox):
    def __init__(self, messages):
        super().__init__(messages)
        self.fetches: list[str] = []

    def fetch(self, uid):
        self.fetches.append(uid)
        return super().fetch(uid)


async def test_one_unparseable_email_does_not_stall_the_poller(db, worker, channels, monkeypatch):
    box = FakeMailbox(
        {
            "1": raw_email(EMAIL, "Broken", "x", "<broken@gmail>"),
            "2": raw_email(EMAIL, "Card", "Where is my card?", "<ok@gmail>"),
        }
    )
    real_parse = email_poller.parse_email

    def parse(raw, **kwargs):
        if b"<broken@gmail>" in raw:
            raise LookupError("unknown encoding: x-bogus")
        return real_parse(raw, **kwargs)

    monkeypatch.setattr(email_poller, "parse_email", parse)
    assert await email_poller.poll_once(worker, since=date(2026, 10, 8), mailbox_factory=box) == 1
    assert box.seen == {"1", "2"}  # the bad one is set aside, not retried every poll
    assert [m.external_message_id for m in await db.scalars(select(Message))] == ["<ok@gmail>"]


async def test_skipped_mail_is_not_downloaded_again(worker, channels):
    worker.settings = worker.settings.model_copy(update={"email_allowed_senders": "*"})
    box = CountingMailbox(
        {"1": raw_email("news@example.com", "Sale", "Buy", "<n@x>", "List-Id: <news.example.com>")}
    )
    skipped: set = set()
    for _ in range(3):
        await email_poller.poll_once(
            worker, since=date(2026, 10, 8), mailbox_factory=box, skipped=skipped
        )
    assert box.fetches == ["1"] and box.seen == set()  # still unread in the user's inbox


async def test_status_write_failure_does_not_kill_the_poller(worker, channels, monkeypatch):
    async def broken(ctx, value):
        raise OSError("database went away")

    monkeypatch.setattr(email_poller, "_write_status", broken)
    # Must not raise: poll_forever would otherwise end silently.
    await email_poller.poll_and_report(
        worker, since=date(2026, 10, 8), mailbox_factory=FakeMailbox({})
    )


async def test_gmail_health_goes_stale_when_the_poller_stops(client, db, worker, channels):
    await email_poller.poll_and_report(
        worker, since=date(2026, 10, 8), mailbox_factory=FakeMailbox({})
    )
    assert (await client.get("/api/health")).json()["channels"]["gmail"] == "ok"
    await db.execute(
        text(
            "UPDATE system_status SET updated_at = now() - interval '10 minutes' "
            "WHERE key = 'channel.gmail'"
        )
    )
    await db.commit()
    assert (await client.get("/api/health")).json()["channels"]["gmail"] == "stale"


async def test_status_callback_racing_the_delivery_commit_is_applied(
    client, db, worker, channels, sessionmaker
):
    await twilio_post(client, "/api/webhooks/twilio/whatsapp", wa_form("SMrace", "hi"))
    await run_all_jobs(worker)
    ack = await db.scalar(select(Message).where(Message.is_template.is_(True)))
    # Simulate the window: Twilio answered with SMlate but the worker has not committed it.
    await db.execute(
        text(
            "UPDATE messages SET external_message_id = NULL, delivery_status = 'queued' "
            "WHERE id = :id"
        ),
        {"id": ack.id},
    )
    await db.commit()

    async def commit_later():
        await asyncio.sleep(0.3)
        async with sessionmaker() as session:
            await session.execute(
                text(
                    "UPDATE messages SET external_message_id = 'SMlate', delivery_status = 'sent' "
                    "WHERE id = :id"
                ),
                {"id": ack.id},
            )
            await session.commit()

    late = asyncio.create_task(commit_later())
    r = await twilio_post(client, "/api/webhooks/twilio/status", status_form("SMlate", "delivered"))
    await late
    assert r.status_code == 200
    await db.refresh(ack)
    assert ack.delivery_status == "delivered"


async def test_retry_forgets_the_old_sid(client, db, worker, channels, auth_headers):
    await twilio_post(client, "/api/webhooks/twilio/whatsapp", wa_form("SMr1", "hi"))
    await run_all_jobs(worker)
    ack = await db.scalar(select(Message).where(Message.is_template.is_(True)))
    old_sid = ack.external_message_id
    await twilio_post(
        client, "/api/webhooks/twilio/status", status_form(old_sid, "failed", "30008")
    )
    assert (
        await client.post(f"/api/messages/{ack.id}/retry", headers=auth_headers)
    ).status_code == 202
    # A late callback for the first attempt must not touch the re-queued message.
    await twilio_post(client, "/api/webhooks/twilio/status", status_form(old_sid, "sent"))
    await db.refresh(ack)
    assert (ack.delivery_status, ack.external_message_id) == ("queued", None)
    await run_all_jobs(worker)
    await db.refresh(ack)
    assert ack.delivery_status == "sent" and ack.external_message_id not in (None, old_sid)


async def test_seed_moves_the_test_contacts_onto_one_customer(
    client, db, worker, channels, settings
):
    # The user emailed before seeding: their address belongs to an auto-created customer.
    box = FakeMailbox({"1": raw_email(EMAIL, "Hi", "Hello", "<early@gmail>")})
    await email_poller.poll_once(worker, since=date(2026, 10, 8), mailbox_factory=box)
    contact = test_contact(
        settings.model_copy(update={"test_contact_phone": PHONE, "test_contact_email": EMAIL})
    )
    await seed(db, TEST_PASSWORD, [contact])
    await db.commit()
    owners = {
        c.kind: c.customer_id
        for c in await db.scalars(
            select(CustomerContact).where(
                CustomerContact.value_normalized.in_([EMAIL, "+919811122334"])
            )
        )
    }
    assert owners["phone"] == owners["email"]


async def test_reply_comes_from_the_number_the_customer_wrote_to(
    client, db, worker, channels, sent_to_twilio
):
    """User bug: Twilio 21654 when the account's sandbox is not +1 415 523 8886."""
    form = {**wa_form("SMbiz1", "My card failed"), "To": "whatsapp:+17005550134"}
    assert (await twilio_post(client, "/api/webhooks/twilio/whatsapp", form)).status_code == 200
    await run_all_jobs(worker)
    inbound = await db.scalar(select(Message).where(Message.direction == "inbound"))
    assert inbound.meta["business_address"] == "whatsapp:+17005550134"
    [ack] = sent_to_twilio
    assert ack["From"] == "whatsapp:+17005550134"
