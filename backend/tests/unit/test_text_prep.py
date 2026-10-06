"""Email cleanup before classification (ARCHITECTURE §6.2, SKILLS A15)."""

from app.ai.text_prep import clean_text, for_intent, for_sentiment, strip_email_noise

GMAIL_REPLY = """Still waiting for my refund, it has been 5 days.

On Mon, 5 Oct 2026 at 10:12, UnifyBank Support <support@unifybank.example> wrote:
> Hi Rahul, we have raised a refund request.
> Thanks
"""

GMAIL_FORWARD = """Please look at this charge I don't recognise.

---------- Forwarded message ---------
From: Alerts <alerts@unifybank.example>
Date: Sun, 4 Oct 2026 at 21:03
Subject: Card transaction
Rs 4,999 spent on card ending 1234
"""

OUTLOOK_REPLY = """My card is blocked again.

Regards,
Priya

________________________________
From: UnifyBank Support <support@unifybank.example>
Sent: Monday, October 5, 2026 9:00 AM
To: Priya Verma
Subject: RE: Card blocked
We have unblocked your card.
"""

OUTLOOK_DESKTOP = """Thanks, that worked.
From: UnifyBank Support
Sent: 05 October 2026 09:00
Subject: Card
Old text
"""

SIGNATURE = """Why was I charged a fee?
--
Amit Rao
Senior Manager, Acme Ltd
+91 99887 76655
"""

MOBILE = """Card not working at the ATM

Sent from my iPhone"""


def test_gmail_reply_keeps_only_new_text():
    assert strip_email_noise(GMAIL_REPLY) == "Still waiting for my refund, it has been 5 days."


def test_gmail_forward_keeps_the_customers_note():
    assert strip_email_noise(GMAIL_FORWARD) == "Please look at this charge I don't recognise."


def test_outlook_web_reply():
    assert strip_email_noise(OUTLOOK_REPLY) == "My card is blocked again.\n\nRegards,\nPriya"


def test_outlook_desktop_header_block():
    assert strip_email_noise(OUTLOOK_DESKTOP) == "Thanks, that worked."


def test_signature_after_dash_dash_space():
    assert strip_email_noise(SIGNATURE) == "Why was I charged a fee?"


def test_mobile_footer_dropped():
    assert strip_email_noise(MOBILE) == "Card not working at the ATM"


def test_inline_quotes_dropped_but_answers_kept():
    body = "> Did the payment go through?\nNo, it failed.\n> Card used?\nThe debit card."
    assert strip_email_noise(body) == "No, it failed.\nThe debit card."


def test_from_line_in_normal_text_is_kept():
    body = "From: my side the payment was done.\nPlease check."
    assert strip_email_noise(body) == body


def test_all_quoted_falls_back_to_full_body():
    body = "> only a quote"
    assert strip_email_noise(body) == "> only a quote"


def test_crlf_line_endings():
    assert strip_email_noise("New text\r\n\r\nOn Mon, X <x@y.z> wrote:\r\n> old") == "New text"


def test_cleanup_only_for_email_channel():
    assert for_intent(GMAIL_REPLY, "email") == "Still waiting for my refund, it has been 5 days."
    assert "wrote:" in for_intent(GMAIL_REPLY, "whatsapp")
    assert for_sentiment(SIGNATURE, "email") == "Why was I charged a fee?"


def test_sentiment_preprocessing_after_cleanup():
    body = "@bank see https://x.io/a\n-- \nsig"
    assert for_sentiment(body, "email") == "@user see http"


def test_clean_text_matches_training_preprocessing():
    assert clean_text("  I can't access my ACCOUNT!!  ") == "i can't access my account!!"
    assert clean_text("₹500 deducted :( @bank #help") == "500 deducted bank help"
    assert clean_text("line\none\ttab") == "line one tab"
