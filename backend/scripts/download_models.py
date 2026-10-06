"""Download the pinned sentiment model to models/sentiment/hf (ARCHITECTURE §8.3).

uv run python -m scripts.download_models

Fetches only what PyTorch inference needs at SENTIMENT_MODEL_REVISION, verifies each
large file against the sha256 Hugging Face publishes for that commit, and records the
weights' sha256 in manifest.json (the app reports its first 12 characters as
model_version). Safe to re-run: complete files are kept and partial ones resume.

Downloads use IPv4 only: on this network large downloads from CloudFront stall over IPv6
(CLAUDE.md). The intent model is not downloaded; it lives in INTENT_MODEL_DIR (§8.2).
"""

import hashlib
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.config import get_settings, setup_process

log = logging.getLogger("download_models")

SENTIMENT_FILES = [
    "config.json",
    "vocab.json",
    "merges.txt",
    "special_tokens_map.json",
    "pytorch_model.bin",
    "README.md",
]
WEIGHTS_FILE = "pytorch_model.bin"
MANIFEST = "manifest.json"
RESOLVE_URL = "https://huggingface.co/{repo}/resolve/{revision}/{file}"
API_URL = "https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true"
MAX_STALLS = 10  # consecutive attempts with no new bytes


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_client() -> httpx.Client:
    return httpx.Client(
        transport=httpx.HTTPTransport(local_address="0.0.0.0", retries=2),  # IPv4 only
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, read=60.0),
        headers={"user-agent": "unifycomm-download-models/1"},
    )


def expected_files(client: httpx.Client, repo: str, revision: str) -> dict[str, dict]:
    """{filename: {"size": int, "sha256": str | None}} for the pinned commit."""
    response = client.get(API_URL.format(repo=repo, revision=revision))
    response.raise_for_status()
    info = response.json()
    if info.get("sha") != revision:
        raise RuntimeError(f"Hub returned commit {info.get('sha')}, expected {revision}")
    return {
        s["rfilename"]: {"size": s.get("size"), "sha256": (s.get("lfs") or {}).get("sha256")}
        for s in info["siblings"]
    }


def _part_size(part: Path) -> int:
    return part.stat().st_size if part.exists() else 0


def download(client: httpx.Client, url: str, dest: Path, size: int | None) -> None:
    """Stream to dest.part, resuming after interruptions, then rename.

    The file is complete only when it reaches the expected size; a stream that ends early
    is resumed like an error. Only consecutive attempts without any progress count
    towards giving up, so a slow, flaky link still finishes. A re-run resumes the .part.
    """
    part = dest.with_name(dest.name + ".part")
    stalls = 0
    while size is None or _part_size(part) < size:
        have = _part_size(part)
        headers = {"Range": f"bytes={have}-"} if have else {}
        error: Exception | None = None
        try:
            with client.stream("GET", url, headers=headers) as response:
                if have and response.status_code != 206:
                    have = 0  # server ignored the range: start over
                response.raise_for_status()
                last_log = time.monotonic()
                with part.open("ab" if have else "wb") as f:
                    for chunk in response.iter_bytes():  # as received: a drop loses nothing
                        f.write(chunk)
                        if time.monotonic() - last_log > 30:
                            log.info(
                                "downloading",
                                extra={
                                    "file": dest.name,
                                    "mb": _part_size(part) >> 20,
                                    "of_mb": (size or 0) >> 20,
                                },
                            )
                            last_log = time.monotonic()
            if size is None:
                break  # unknown size: one complete response is the whole file
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            error = exc

        stalls = 0 if _part_size(part) > have else stalls + 1
        if stalls >= MAX_STALLS:
            raise RuntimeError(f"no progress on {dest.name} after {MAX_STALLS} attempts")
        if error is not None or stalls:
            log.warning(
                "download interrupted; resuming",
                extra={
                    "file": dest.name,
                    "mb": _part_size(part) >> 20,
                    "error": type(error).__name__ if error else "short read",
                },
            )
            time.sleep(min(2 ** max(stalls, 1), 30))
    part.replace(dest)


def main() -> int:
    settings = get_settings()
    setup_process(settings)  # truststore: this network re-signs TLS
    logging.getLogger("httpx").setLevel(logging.WARNING)  # request logs carry signed CDN URLs
    repo, revision = settings.sentiment_model_id, settings.sentiment_model_revision
    if len(revision) != 40:
        log.error("SENTIMENT_MODEL_REVISION must be a full 40-character commit hash")
        return 2
    target = settings.sentiment_model_dir
    target.mkdir(parents=True, exist_ok=True)

    with make_client() as client:
        expected = expected_files(client, repo, revision)
        for name in SENTIMENT_FILES:
            meta = expected.get(name)
            if meta is None:
                log.error("file not in the pinned commit", extra={"file": name})
                return 1
            dest = target / name
            if dest.exists() and (meta["size"] is None or dest.stat().st_size == meta["size"]):
                if meta["sha256"] is None or sha256_of(dest) == meta["sha256"]:
                    continue
                dest.unlink()
            log.info("fetching", extra={"file": name, "mb": (meta["size"] or 0) >> 20})
            download(
                client,
                RESOLVE_URL.format(repo=repo, revision=revision, file=name),
                dest,
                meta["size"],
            )
            if meta["sha256"] and sha256_of(dest) != meta["sha256"]:
                dest.unlink()
                log.error("checksum mismatch; deleted", extra={"file": name})
                return 1

    weights_sha = sha256_of(target / WEIGHTS_FILE)
    manifest = {
        "repo_id": repo,
        "revision": revision,
        "weights_file": WEIGHTS_FILE,
        "weights_sha256": weights_sha,
        "license": "CC BY 4.0",
        "downloaded_at": datetime.now(UTC).isoformat(),
    }
    (target / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    log.info(
        "sentiment model ready", extra={"dir": str(target), "weights_sha256": weights_sha[:12]}
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
