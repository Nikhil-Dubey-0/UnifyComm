"""Gmail parsing, MIME building and SMTP error mapping (ARCHITECTURE §9.2.1). No network."""

import smtplib
from email import message_from_bytes
from email.policy import default as default_policy

import pytest
from pydantic import SecretStr

from app.ai import text_prep
from app.channels.base import InboundMessage, OutboundMessage
from app.channels.gmail import (
    ATTACHMENT_ONLY_BODY,
    GmailAdapter,
    Skip,
    build_mime,
    html_to_text,
    parse_email,
)
from app.services.outbound import email_thread_meta

OWN = "support.unifycomm@gmail.com"
ALLOWED = ["priya.tester@gmail.com"]

GMAIL_REPLY = b"""From: Priya Tester <Priya.Tester@gmail.com>
To: support.unifycomm@gmail.com
Subject: Re: Card not received
Date: Wed, 07 Oct 2026 14:05:00 +0530
Message-ID: <CAF2=abc123@mail.gmail.com>
In-Reply-To: <first@unifycomm>
References: <root@mail.gmail.com> <first@unifycomm>
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="b1"

--b1
Content-Type: text/plain; charset="UTF-8"

Still no card. It has been ten days.

On Tue, 6 Oct 2026 at 10:00, UnifyComm Support <support.unifycomm@gmail.com> wrote:
> We are checking the dispatch status.
--b1
Content-Type: text/html; charset="UTF-8"

<div>Still no card. It has been ten days.</div>
--b1--
"""

OUTLOOK_HTML_ONLY = b"""From: priya.tester@gmail.com
To: support.unifycomm@gmail.com
Subject: Refund
Message-ID: <outlook-1@example.com>
MIME-Version: 1.0
Content-Type: text/html; charset="UTF-8"

<html><head><style>p{color:red}</style></head><body>
<p>I was charged twice &amp; need a refund.</p><br>
<div>Thanks</div>
<hr><div><b>From:</b> Support<br><b>Sent:</b> Monday</div></body></html>
"""


def parse(raw: bytes, allowed=ALLOWED, fallback="gmail-1-7"):
    return parse_email(raw, own_address=OWN, allowed=allowed, fallback_id=fallback)


def test_gmail_reply_is_parsed_with_threading_metadata():
    inbound = parse(GMAIL_REPLY)
    assert isinstance(inbound, InboundMessage)
    assert (inbound.channel, inbound.provider, inbound.sender_kind) == ("email", "gmail", "email")
    assert inbound.sender_raw == "priya.tester@gmail.com"  # lowercased for identity
    assert inbound.sender_name == "Priya Tester"
    assert inbound.external_id == "<CAF2=abc123@mail.gmail.com>"
    assert inbound.body.startswith("Still no card.")
    assert "> We are checking" in inbound.body  # stored as received
    assert inbound.metadata == {
        "subject": "Re: Card not received",
        "message_id": "<CAF2=abc123@mail.gmail.com>",
        "in_reply_to": "<first@unifycomm>",
        "references": ["<root@mail.gmail.com>", "<first@unifycomm>"],
    }
    assert inbound.provider_timestamp is not None
    # The models see only the new text (Session 3 cleanup).
    assert text_prep.for_intent(inbound.body, "email") == "Still no card. It has been ten days."


def test_html_only_email_is_converted_to_text():
    inbound = parse(OUTLOOK_HTML_ONLY)
    assert isinstance(inbound, InboundMessage)
    assert inbound.body.startswith("I was charged twice & need a refund.\n\nThanks")
    assert "color:red" not in inbound.body
    assert (
        text_prep.for_intent(inbound.body, "email") == "I was charged twice & need a refund. Thanks"
    )


@pytest.mark.parametrize(
    "header,reason",
    [
        ("From: someone.else@gmail.com", "sender not allowlisted"),
        (f"From: UnifyComm <{OWN}>", "own address"),
        ("From:", "no sender"),
    ],
)
def test_senders_that_are_skipped(header, reason):
    raw = f"{header}\nSubject: hi\nMessage-ID: <x@y>\n\nhello\n".encode()
    assert parse(raw) == Skip(reason)


@pytest.mark.parametrize(
    "extra",
    ["Auto-Submitted: auto-replied", "Precedence: bulk", "List-Id: <news.example.com>"],
)
def test_automatic_mail_is_never_ingested(extra):
    raw = f"From: priya.tester@gmail.com\n{extra}\nMessage-ID: <x@y>\n\nhello\n".encode()
    assert parse(raw) == Skip("automatic mail")


def test_wildcard_allowlist_and_missing_message_id():
    raw = b"From: anyone@example.org\nSubject: hi\n\nhello\n"
    assert parse(raw) == Skip("sender not allowlisted")
    inbound = parse(raw, allowed=["*"], fallback="gmail-55-9")
    assert isinstance(inbound, InboundMessage)
    assert inbound.external_id == "gmail-55-9" and inbound.metadata["message_id"] is None


def test_attachment_only_email_gets_a_placeholder():
    raw = (
        b"From: priya.tester@gmail.com\nMessage-ID: <a@b>\nMIME-Version: 1.0\n"
        b'Content-Type: multipart/mixed; boundary="m"\n\n--m\nContent-Type: image/png\n'
        b"Content-Transfer-Encoding: base64\n\niVBORw0KGgo=\n--m--\n"
    )
    inbound = parse(raw)
    assert isinstance(inbound, InboundMessage) and inbound.body == ATTACHMENT_ONLY_BODY


def test_html_to_text_drops_scripts_and_keeps_lines():
    assert html_to_text("<script>x()</script><p>One</p><p>Two&nbsp;three</p>") == (
        "One\nTwo\xa0three"
    )


def test_thread_meta_builds_reply_headers():
    inbound = parse(GMAIL_REPLY)
    meta = email_thread_meta(inbound.metadata)
    assert meta == {
        "subject": "Re: Card not received",  # not "Re: Re:"
        "in_reply_to": "<CAF2=abc123@mail.gmail.com>",
        "references": [
            "<root@mail.gmail.com>",
            "<first@unifycomm>",
            "<CAF2=abc123@mail.gmail.com>",
        ],
    }
    assert email_thread_meta({"subject": "Refund"})["subject"] == "Re: Refund"
    assert email_thread_meta(None) == {}


def out(**meta) -> OutboundMessage:
    return OutboundMessage(
        message_id=7, channel="email", to="priya.tester@gmail.com", body="Hello", metadata=meta
    )


def test_build_mime_sets_threading_headers():
    mime = build_mime(
        out(subject="Re: Refund", in_reply_to="<a@x>", references=["<r@x>", "<a@x>"]),
        from_address=OWN,
        from_name="UnifyComm Support",
    )
    assert mime["From"] == f"UnifyComm Support <{OWN}>"
    assert mime["To"] == "priya.tester@gmail.com"
    assert mime["Subject"] == "Re: Refund"
    assert mime["In-Reply-To"] == "<a@x>"
    assert mime["References"] == "<r@x> <a@x>"
    assert mime["Message-ID"].endswith("@gmail.com>")
    assert mime["Auto-Submitted"] == "no"
    assert mime.get_content().strip() == "Hello"


def test_template_is_marked_auto_replied():
    template = out().model_copy(update={"is_template": True})
    mime = build_mime(template, from_address=OWN, from_name="S")
    assert mime["Auto-Submitted"] == "auto-replied"
    assert mime["Subject"] == "Your message to our support team"
    assert mime["In-Reply-To"] is None


class FakeSMTP:
    sent: list = []
    fail: Exception | None = None

    def __init__(self, host, port, timeout):
        self.calls = [("connect", host, port)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context):
        assert context.verify_mode.name == "CERT_REQUIRED"  # certificates always verified

    def login(self, user, password):
        assert " " not in password

    def send_message(self, mime):
        if FakeSMTP.fail:
            raise FakeSMTP.fail
        FakeSMTP.sent.append(mime)


@pytest.fixture
def adapter(settings, monkeypatch):
    monkeypatch.setattr("app.channels.gmail.smtplib.SMTP", FakeSMTP)
    FakeSMTP.sent, FakeSMTP.fail = [], None
    configured = settings.model_copy(
        update={"email_address": OWN, "email_app_password": SecretStr("abcd efgh ijkl mnop")}
    )
    return GmailAdapter(configured)


async def test_send_returns_the_message_id(adapter):
    result = await adapter.send(out(subject="Re: Refund"))
    assert result.ok and not result.delivered
    [mime] = FakeSMTP.sent
    assert result.external_id == mime["Message-ID"]
    assert message_from_bytes(mime.as_bytes(), policy=default_policy)["To"] == (
        "priya.tester@gmail.com"
    )


@pytest.mark.parametrize(
    "error,retryable",
    [
        (smtplib.SMTPRecipientsRefused({"x@y": (550, b"no")}), False),
        (smtplib.SMTPAuthenticationError(535, b"bad credentials"), False),
        (smtplib.SMTPDataError(554, b"rejected"), False),
        (smtplib.SMTPDataError(451, b"try later"), True),
        # Disconnects and timeouts while sending are ambiguous: not retried automatically.
        (smtplib.SMTPServerDisconnected("gone"), False),
        (TimeoutError(), False),
    ],
)
async def test_send_errors(adapter, error, retryable):
    FakeSMTP.fail = error
    result = await adapter.send(out())
    assert not result.ok and result.retryable is retryable
    assert result.error.startswith("SMTP")


# --- review fixes (Session 5) ------------------------------------------------------------


def test_unknown_charset_is_decoded_leniently():
    raw = (
        b"From: priya.tester@gmail.com\nMessage-ID: <cs@x>\nMIME-Version: 1.0\n"
        b'Content-Type: text/plain; charset="x-bogus"\n\nMy card \xe9 failed\n'
    )
    inbound = parse(raw)
    assert isinstance(inbound, InboundMessage)
    assert inbound.body.startswith("My card") and inbound.body.endswith("failed")


def test_message_id_is_stable_per_message():
    """A resend of the same message keeps its Message-ID, so mail clients can dedupe it."""
    first = build_mime(out(), from_address=OWN, from_name="S")
    second = build_mime(out(), from_address=OWN, from_name="S")
    assert first["Message-ID"] == second["Message-ID"] == "<unifycomm.7@gmail.com>"


class TimeoutDuringSend(FakeSMTP):
    def send_message(self, mime):
        raise TimeoutError()


class RefusedAtConnect(FakeSMTP):
    def __init__(self, host, port, timeout):
        raise ConnectionRefusedError()


@pytest.mark.parametrize(
    "smtp_class,retryable",
    [
        # The server may already have accepted the message: never resend automatically.
        (TimeoutDuringSend, False),
        # Nothing was sent yet: safe to retry.
        (RefusedAtConnect, True),
    ],
)
async def test_only_errors_before_sending_are_retried(adapter, monkeypatch, smtp_class, retryable):
    monkeypatch.setattr("app.channels.gmail.smtplib.SMTP", smtp_class)
    result = await adapter.send(out())
    assert not result.ok and result.retryable is retryable


def test_header_values_from_customers_cannot_break_replies():
    """Security review: an encoded newline in the Subject must neither inject a header
    nor make every reply in the conversation fail."""
    raw = (
        b"From: priya.tester@gmail.com\nMessage-ID: <h@x>\n"
        b"Subject: =?utf-8?q?Refund=0ABcc:_victim@x.com?=\n\nhello\n"
    )
    inbound = parse(raw)
    assert isinstance(inbound, InboundMessage)
    assert inbound.metadata["subject"] == "Refund Bcc: victim@x.com"
    mime = build_mime(
        out(subject="Re: a\r\nBcc: v@x.com", in_reply_to="<m@x>\n", references=["<r@x>\r\n"]),
        from_address=OWN,
        from_name="S",
    )
    assert mime["Bcc"] is None
    assert mime["Subject"] == "Re: a Bcc: v@x.com"
    assert mime["In-Reply-To"] == "<m@x>" and mime["References"] == "<r@x>"
