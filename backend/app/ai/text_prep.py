"""Text preparation before classification (ARCHITECTURE §6.2). Torch-free.

Session 1 keeps this minimal; Session 3 adds email quote/signature stripping and
token-based truncation. PII redaction for LLM calls arrives in Session 4 (§7.7).
"""

import re

_WS = re.compile(r"\s+")
_MENTION = re.compile(r"@\w+")
_URL = re.compile(r"https?://\S+|www\.\S+")

# Character caps keep model inputs bounded until token-based truncation lands.
INTENT_MAX_CHARS = 512
SENTIMENT_MAX_CHARS = 2000


def collapse_whitespace(text: str) -> str:
    return _WS.sub(" ", text).strip()


def for_intent(body: str) -> str:
    return collapse_whitespace(body)[:INTENT_MAX_CHARS]


def for_sentiment(body: str) -> str:
    """cardiffnlp model card preprocessing: @mention → @user, URL → http."""
    text = _URL.sub("http", body)
    text = _MENTION.sub("@user", text)
    return collapse_whitespace(text)[:SENTIMENT_MAX_CHARS]
