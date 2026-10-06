"""Logging setup: standard logging, structured `extra` fields appended as key=value."""

import logging
import re

_TOKEN_IN_QUERY = re.compile(r"(\btoken=)[^&\s\"']+")
# uvicorn logs request paths; the WebSocket JWT travels in the query string (§11).
UVICORN_LOGGERS = ("uvicorn.access", "uvicorn.error")

_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS}
        if not extras:
            return base
        return base + " " + " ".join(f"{k}={v}" for k, v in sorted(extras.items()))


class RedactTokenFilter(logging.Filter):
    """Replaces `token=<jwt>` in a log line with `token=[redacted]`."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "token=" in message:
            record.msg, record.args = _TOKEN_IN_QUERY.sub(r"\1[redacted]", message), None
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(KeyValueFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for name in UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactTokenFilter) for f in logger.filters):
            logger.addFilter(RedactTokenFilter())
