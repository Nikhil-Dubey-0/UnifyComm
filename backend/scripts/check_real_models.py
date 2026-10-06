"""Session 3 exit check against a running api and a worker in AI_MODE=real (§16).

uv run python -m scripts.check_real_models [--base-url http://localhost:8000]

Sends the golden sentences from the simulator as a new sender, waits for each message's
intent and sentiment, and reports time-to-labels (target < 2 s), model latency and the
worker's memory. The models must already be loaded (the worker preloads them at startup).
"""

import argparse
import asyncio
import statistics
import subprocess
import sys
import time
import uuid

import httpx

from app.config import get_settings

DEADLINE_S = 2.0
SENTENCES = [
    "I can't access my account anymore",
    "What's the exchange rate for USD to EUR?",
    "My card was stolen yesterday",
    "I was charged twice and nobody is helping me",
    "I love the new mobile banking features!",
    "My payment failed but the money was deducted.",
]


class CheckFailed(Exception):
    pass


def worker_memory_mb(worker_id: str) -> float | None:
    """Working set of the worker process (Windows), from the pid in its worker id."""
    pid = worker_id.rsplit("-", 1)[-1]
    if not pid.isdigit():
        return None
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", f"(Get-Process -Id {pid}).WorkingSet64"],
        capture_output=True,
        text=True,
        check=False,
    )
    return int(out.stdout.strip()) / 2**20 if out.stdout.strip().isdigit() else None


async def run(base_url: str) -> None:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as http:
        health = (await http.get("/api/health")).json()
        if health["ai_mode"] != "real":
            raise CheckFailed(f"api reports ai_mode={health['ai_mode']}; set AI_MODE=real")
        token = (
            await http.post(
                "/api/auth/login",
                json={
                    "email": "agent@unifycomm.local",
                    "password": settings.seed_agent_password.get_secret_value(),
                },
            )
        ).json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        sender = f"+91 9{uuid.uuid4().int % 10**9:09d}"

        waits, intent_ms, sentiment_ms = [], [], []
        for text in SENTENCES:
            started = time.perf_counter()
            r = (
                await http.post(
                    "/api/channels/simulator/inbound",
                    json={
                        "channel": "whatsapp",
                        "from": sender,
                        "body": text,
                        "sender_name": "Model check",
                    },
                )
            ).json()
            ai = None
            while time.perf_counter() - started < 15:
                detail = (
                    await http.get(f"/api/conversations/{r['conversation_id']}", headers=auth)
                ).json()
                msg = next(m for m in detail["messages"] if m["id"] == r["message_id"])
                if msg["ai"]["intent"] and msg["ai"]["sentiment"]:
                    ai = msg["ai"]
                    break
                await asyncio.sleep(0.05)
            if ai is None:
                raise CheckFailed(f"no labels after 15 s for {text!r}")
            wait = time.perf_counter() - started
            intent, sentiment = ai["intent"], ai["sentiment"]
            if (
                "fake" in intent["model_version"]
                or intent["status"] != "ok"
                or sentiment["status"] != "ok"
            ):
                raise CheckFailed(f"not real model output: {intent} / {sentiment}")
            waits.append(wait)
            intent_ms.append(intent["latency_ms"])
            sentiment_ms.append(sentiment["latency_ms"])
            print(
                f"{wait:5.2f}s  {text!r:52} "
                f"intent={intent['label']} ({intent['confidence']:.2f}, {intent['category']}) "
                f"sentiment={sentiment['label']} ({sentiment['confidence']:.2f})"
            )

        print(
            f"\nmodels: {intent['model_name']}@{intent['model_version']}, "
            f"{sentiment['model_name']}@{sentiment['model_version']}"
        )
        print(f"time to labels: median {statistics.median(waits):.2f}s, max {max(waits):.2f}s")
        print(f"intent latency ms: median {statistics.median(intent_ms)}, max {max(intent_ms)}")
        print(
            "sentiment latency ms: "
            f"median {statistics.median(sentiment_ms)}, max {max(sentiment_ms)}"
        )
        worker_id = await _worker_id()
        mem = worker_memory_mb(worker_id) if worker_id else None
        print(f"worker memory: {mem:.0f} MB" if mem else "worker memory: unknown")
        if max(waits) >= DEADLINE_S:
            raise CheckFailed(f"slowest message took {max(waits):.2f}s (target < {DEADLINE_S}s)")
    print("PASS  real labels within 2 s for every message")


async def _worker_id() -> str | None:
    # The heartbeat row holds the worker id; /health exposes only its time, so read the DB.
    from sqlalchemy import select

    from app.db import make_engine, make_sessionmaker
    from app.models import SystemStatus
    from app.services.system import HEARTBEAT_KEY

    engine = make_engine(get_settings().database_url, null_pool=True)
    try:
        async with make_sessionmaker(engine)() as session:
            row = await session.scalar(
                select(SystemStatus).where(SystemStatus.key == HEARTBEAT_KEY)
            )
            return row.value.get("worker_id") if row else None
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.base_url))
    except (CheckFailed, httpx.HTTPError, OSError) as exc:
        print(f"FAIL  {exc!r}")
        sys.exit(1)


if __name__ == "__main__":
    main()
