import logging

from app.log import UVICORN_LOGGERS, RedactTokenFilter, configure_logging


def _record(msg: str, *args) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, msg, args, None)


def test_websocket_token_is_redacted():
    record = _record('%s - "WebSocket %s" [accepted]', "127.0.0.1:5000", "/ws?token=eyJ.abc.def")
    RedactTokenFilter().filter(record)
    assert record.getMessage() == '127.0.0.1:5000 - "WebSocket /ws?token=[redacted]" [accepted]'


def test_other_query_params_survive():
    record = _record("GET /x?a=1&token=secret&b=2")
    RedactTokenFilter().filter(record)
    assert record.getMessage() == "GET /x?a=1&token=[redacted]&b=2"


def test_configure_logging_installs_filter_once():
    configure_logging()
    configure_logging()
    for name in UVICORN_LOGGERS:
        filters = [f for f in logging.getLogger(name).filters if isinstance(f, RedactTokenFilter)]
        assert len(filters) == 1
