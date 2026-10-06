"""Text preparation before classification (ARCHITECTURE §6.2). Torch-free.

Only the text sent to the models is cleaned; the original body is stored and shown as
received. Token limits (intent 64, sentiment 256) are enforced by the tokenizers; the
character caps here only bound the work done before tokenizing.
"""

import re

_WS = re.compile(r"\s+")
_MENTION = re.compile(r"@\w+")
_URL = re.compile(r"https?://\S+|www\.\S+")

INTENT_MAX_CHARS = 512
SENTIMENT_MAX_CHARS = 2000

# A line that starts the quoted part of a reply or forward; everything from it on is
# history, not the customer's new message.
_HISTORY_MARKERS = [
    re.compile(r"^\s*On .{3,200}wrote:\s*$", re.IGNORECASE),  # Gmail, Apple Mail
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE),  # Outlook
    re.compile(r"^\s*-{2,}\s*Forwarded message\s*-{2,}\s*$", re.IGNORECASE),  # Gmail forward
    re.compile(r"^\s*Begin forwarded message:\s*$", re.IGNORECASE),  # Apple Mail forward
    re.compile(r"^\s*_{10,}\s*$"),  # Outlook web separator line
]
# Outlook desktop: "From: ..." followed within two lines by "Sent:" or "Date:".
_OUTLOOK_FROM = re.compile(r"^\s*\*?From:\*?\s", re.IGNORECASE)
_OUTLOOK_SENT = re.compile(r"^\s*\*?(Sent|Date):\*?\s", re.IGNORECASE)
_SIGNATURE = re.compile(r"^-- ?$")  # RFC 3676 signature separator
_MOBILE_FOOTER = re.compile(r"^\s*Sent from my \w+", re.IGNORECASE)


def collapse_whitespace(text: str) -> str:
    return _WS.sub(" ", text).strip()


def strip_email_noise(body: str) -> str:
    """Keep only the new part of an email: drop quoted history, signature and
    'Sent from my phone' footers. Falls back to the full body if nothing is left."""
    lines = body.replace("\r\n", "\n").split("\n")
    kept: list[str] = []
    for i, line in enumerate(lines):
        if any(p.match(line) for p in _HISTORY_MARKERS):
            break
        if _OUTLOOK_FROM.match(line) and any(_OUTLOOK_SENT.match(n) for n in lines[i + 1 : i + 3]):
            break
        if _SIGNATURE.match(line.rstrip("\r")):
            break
        if line.lstrip().startswith(">") or _MOBILE_FOOTER.match(line):
            continue
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    return cleaned or body.strip()


def for_intent(body: str, channel: str = "") -> str:
    text = strip_email_noise(body) if channel == "email" else body
    return collapse_whitespace(text)[:INTENT_MAX_CHARS]


def for_sentiment(body: str, channel: str = "") -> str:
    """cardiffnlp model card preprocessing: @mention → @user, URL → http."""
    text = strip_email_noise(body) if channel == "email" else body
    text = _URL.sub("http", text)
    text = _MENTION.sub("@user", text)
    return collapse_whitespace(text)[:SENTIMENT_MAX_CHARS]


def clean_text(text: str) -> str:
    """The intent model's training preprocessing (clean_text_v1, ARCHITECTURE §8.2):
    lowercase, keep [a-z0-9 whitespace . , ! ? ' -], collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s\.\,\!\?\'\-]", "", text)
    return re.sub(r"\s+", " ", text).strip()
