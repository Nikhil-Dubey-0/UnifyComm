"""Resumable downloads (scripts/download_models.py) on a flaky network."""

import httpx
import pytest

from scripts import download_models
from scripts.download_models import MAX_STALLS, download

PAYLOAD = bytes(range(256)) * 40  # 10,240 bytes


class FlakyStream(httpx.SyncByteStream):
    """Yields `data`, then optionally fails mid-stream like a dropped connection."""

    def __init__(self, data: bytes, fail: bool) -> None:
        self.data, self.fail = data, fail

    def __iter__(self):
        yield self.data
        if self.fail:
            raise httpx.ReadError("connection reset")


def server(chunk: int, fail: bool):
    """Serves at most `chunk` bytes per request, honouring Range."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        start = 0
        if "range" in request.headers:
            start = int(request.headers["range"].removeprefix("bytes=").rstrip("-"))
        calls.append(start)
        body = PAYLOAD[start : start + chunk]
        return httpx.Response(206 if start else 200, stream=FlakyStream(body, fail))

    return handler, calls


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(download_models.time, "sleep", lambda s: None)


def test_many_interruptions_with_progress_still_finish(tmp_path):
    handler, calls = server(chunk=500, fail=True)  # 21 dropped connections
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        download(client, "https://hub/x", tmp_path / "w.bin", len(PAYLOAD))
    assert (tmp_path / "w.bin").read_bytes() == PAYLOAD
    assert len(calls) > MAX_STALLS
    assert not (tmp_path / "w.bin.part").exists()


def test_stream_that_ends_early_is_resumed_not_kept(tmp_path):
    handler, calls = server(chunk=4000, fail=False)  # clean but short responses
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        download(client, "https://hub/x", tmp_path / "w.bin", len(PAYLOAD))
    assert (tmp_path / "w.bin").read_bytes() == PAYLOAD
    assert calls == [0, 4000, 8000]


def test_existing_part_file_is_resumed(tmp_path):
    (tmp_path / "w.bin.part").write_bytes(PAYLOAD[:6000])
    handler, calls = server(chunk=len(PAYLOAD), fail=False)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        download(client, "https://hub/x", tmp_path / "w.bin", len(PAYLOAD))
    assert calls == [6000]
    assert (tmp_path / "w.bin").read_bytes() == PAYLOAD


def test_gives_up_when_nothing_arrives(tmp_path):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network unreachable")

    with httpx.Client(transport=httpx.MockTransport(down)) as client:
        with pytest.raises(RuntimeError, match="no progress"):
            download(client, "https://hub/x", tmp_path / "w.bin", len(PAYLOAD))
    assert not (tmp_path / "w.bin").exists()
