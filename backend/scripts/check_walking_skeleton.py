"""Session 1 exit check against a running api and worker (ARCHITECTURE §16).

Start the api (port 8000) and the worker, seed the database, then:
    uv run python -m scripts.check_walking_skeleton [--base-url http://localhost:8000]

Checks: health and worker heartbeat; a simulator message shows fake intent and sentiment
within 2 s; a WebSocket client receives message.created and message.analyzed; a duplicate
external ID is ignored; an agent reply is delivered back to the simulator thread; and
importing the api does not import torch.
"""

import argparse
import asyncio
import json
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime

import httpx
from websockets.asyncio.client import connect

from app.config import BACKEND_DIR, get_settings

ANALYSIS_DEADLINE_S = 2.0
RAHUL_WHATSAPP = "+919876543210"


class CheckFailed(Exception):
    pass


def ok(name: str, detail: str = "") -> None:
    print(f"PASS  {name}" + (f"  ({detail})" if detail else ""))


def expect(condition: bool, name: str, detail: str = "") -> None:
    if not condition:
        raise CheckFailed(f"{name}: {detail}")
    ok(name, detail)


async def run(base_url: str) -> None:
    settings = get_settings()
    ws_url = base_url.replace("http", "ws", 1) + "/ws"
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as http:
        health = (await http.get("/api/health")).json()
        expect(health["db"] == "ok", "health: database reachable")
        beat = health["worker_heartbeat_at"]
        age = (datetime.now(UTC) - datetime.fromisoformat(beat)).total_seconds() if beat else None
        expect(age is not None and age < 30, "health: worker heartbeat is fresh", f"{age=}")

        login = await http.post(
            "/api/auth/login",
            json={
                "email": "agent@unifycomm.local",
                "password": settings.seed_agent_password.get_secret_value(),
            },
        )
        expect(login.status_code == 200, "auth: seeded agent can log in", str(login.status_code))
        token = login.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        async with connect(f"{ws_url}?token={token}") as ws:
            hello = json.loads(await ws.recv())
            expect(hello == {"type": "hello"}, "ws: hello on connect")

            external_id = f"check-{uuid.uuid4().hex[:12]}"
            started = time.perf_counter()
            created = await http.post(
                "/api/channels/simulator/inbound",
                json={
                    "channel": "whatsapp",
                    "from": RAHUL_WHATSAPP,
                    "body": "My payment failed but the money was deducted.",
                    "external_id": external_id,
                },
            )
            expect(created.status_code == 201, "ingest: simulator POST accepted")
            ids = created.json()
            message_id, conversation_id = ids["message_id"], ids["conversation_id"]

            ai = None
            while time.perf_counter() - started < ANALYSIS_DEADLINE_S + 3:
                detail = (
                    await http.get(f"/api/conversations/{conversation_id}", headers=auth)
                ).json()
                msg = next(m for m in detail["messages"] if m["id"] == message_id)
                if msg["ai"]["intent"] and msg["ai"]["sentiment"]:
                    ai = msg["ai"]
                    break
                await asyncio.sleep(0.05)
            elapsed = time.perf_counter() - started
            expect(ai is not None, "worker: message analysed")
            expect(
                elapsed < ANALYSIS_DEADLINE_S,
                "worker: AI labels visible within 2 s",
                f"{elapsed:.2f}s, intent={ai['intent']['label']} "
                f"({ai['intent']['category']}), sentiment={ai['sentiment']['label']}, "
                f"model={ai['intent']['model_version']}",
            )
            expect(
                detail["conversation"]["category"] == "payments_billing",
                "routing: conversation categorised",
                f"category={detail['conversation']['category']}, "
                f"priority={detail['conversation']['priority']}",
            )

            seen: set[str] = set()
            async with asyncio.timeout(5):
                while not {"message.created", "message.analyzed"} <= seen:
                    event = json.loads(await ws.recv())
                    if event.get("message_id") == message_id:
                        seen.add(event["type"])
            ok("ws: received message.created and message.analyzed", ", ".join(sorted(seen)))

            dup = await http.post(
                "/api/channels/simulator/inbound",
                json={
                    "channel": "whatsapp",
                    "from": RAHUL_WHATSAPP,
                    "body": "My payment failed but the money was deducted.",
                    "external_id": external_id,
                },
            )
            expect(
                dup.status_code == 200
                and dup.json()["duplicate"] is True
                and dup.json()["message_id"] == message_id,
                "ingest: duplicate external ID ignored",
                f"status={dup.status_code}",
            )

            sent = await http.post(
                f"/api/conversations/{conversation_id}/send",
                json={"channel": "whatsapp", "body": "Sorry about that, we are checking."},
                headers={**auth, "Idempotency-Key": f"check-{uuid.uuid4()}"},
            )
            expect(sent.status_code == 201, "send: agent reply accepted")
            reply_id = sent.json()["message"]["id"]
            status = None
            async with asyncio.timeout(5):
                while status != "delivered":
                    thread = (
                        await http.get(
                            "/api/simulator/thread",
                            params={"channel": "whatsapp", "address": RAHUL_WHATSAPP},
                            headers=auth,
                        )
                    ).json()
                    status = next(
                        (m["delivery_status"] for m in thread if m["id"] == reply_id), None
                    )
                    await asyncio.sleep(0.05)
            ok("send: reply delivered to the simulator thread")


def check_boundary() -> None:
    probe = subprocess.run(
        [sys.executable, "-c", "import app.main, sys; print('torch' in sys.modules)"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    expect(probe.stdout.strip().splitlines()[-1] == "False", "boundary: api does not import torch")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.base_url))
        check_boundary()
    except (CheckFailed, TimeoutError, httpx.HTTPError, OSError) as exc:
        print(f"FAIL  {exc!r}")
        sys.exit(1)
    print("All Session 1 exit checks passed.")


if __name__ == "__main__":
    main()
