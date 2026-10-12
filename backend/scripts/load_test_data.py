"""Load synthetic traffic and time the main read endpoints (ARCHITECTURE §16, Session 5).

  uv run python -m scripts.load_test_data load --customers 150   # needs the DB
  # wait until the worker has drained the jobs (analysis, acknowledgements, deliveries)
  uv run python -m scripts.load_test_data spread --days 7         # backdate for the charts
  uv run python -m scripts.load_test_data measure                 # needs the api running
  uv run python -m scripts.load_test_data purge                   # delete only the load data

`load` ingests through services/ingest.py on the simulator provider only (never a real
channel), with at most 4 messages per conversation so no summary (OpenAI) is triggered.
`spread` moves each synthetic conversation, with everything that belongs to it (messages,
AI results, compliance checks), to a point in the last --days days. The offset comes from
a hash of the conversation id, so running it again gives the same layout.
Senders are "+91 90000 3xxxx" and "Load <n>"; `seed --reset` removes them.
`measure` logs in and reports p50/p95 for the inbox, a conversation, the compliance log and
the metrics summary.
"""

import argparse
import asyncio
import random
import statistics
import time

import httpx
from sqlalchemy import text

from app.channels.simulator import parse_inbound
from app.config import get_settings, setup_process
from app.db import make_engine, make_sessionmaker
from app.enums import Channel
from app.services import ingest

MESSAGES = [
    "My payment failed but the money was deducted.",
    "I was charged twice for the same transaction",
    "My card was stolen yesterday, please block it",
    "There is a transaction I don't recognise on my card",
    "When will my new card arrive?",
    "My card is not working at the ATM",
    "I forgot my passcode and cannot log in",
    "Why is my account blocked?",
    "How do I change my PIN?",
    "The transfer to my brother is still pending",
    "My top up failed",
    "What is the exchange rate for USD to INR?",
    "I need a refund for a cancelled order",
    "What is my credit limit?",
    "Can I increase my credit limit?",
    "How do I verify my identity?",
    "This is the worst bank I have ever used",
    "Thank you, that solved it!",
    "Any update?",
    "Hello",
    "Is there a fee for international transfers?",
    "My salary has not shown up in my balance",
    "Can you help me book a flight?",
    "I lost my phone with the banking app on it",
]
CHANNELS = [Channel.whatsapp, Channel.whatsapp, Channel.sms, Channel.email]


async def load(customers: int, seed: int) -> None:
    settings = get_settings()
    setup_process(settings)
    rng = random.Random(seed)
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    count = 0
    started = time.perf_counter()
    try:
        for n in range(customers):
            phone = f"+91 90000 3{n:04d}"
            email = f"load{n:04d}@example.com"
            for _ in range(rng.randint(1, 4)):
                channel = rng.choice(CHANNELS)
                inbound = parse_inbound(
                    channel=channel,
                    sender=email if channel == Channel.email else phone,
                    body=rng.choice(MESSAGES),
                    sender_name=f"Load {n:04d}",
                    subject="Help" if channel == Channel.email else None,
                )
                async with sessionmaker() as session:
                    await ingest.ingest(session, inbound, settings)
                count += 1
        took = time.perf_counter() - started
        print(f"ingested {count} messages for {customers} customers in {took:.1f} s")
    finally:
        await engine.dispose()


# delta = (now - hashed offset) - the conversation's first message time.
_SHIFT = """
CREATE TEMP TABLE shift ON COMMIT DROP AS
SELECT c.id,
       (now() - (abs(hashtext(c.id::text)) % 1000) / 1000.0 * :days * interval '1 day')
         - min(m.created_at) AS delta
FROM conversations c
JOIN customers u ON u.id = c.customer_id
JOIN messages m ON m.conversation_id = c.id
WHERE u.display_name LIKE 'Load %'
GROUP BY c.id
"""
_APPLY = [
    """UPDATE conversations c SET created_at = c.created_at + s.delta,
           last_activity_at = c.last_activity_at + s.delta,
           last_inbound_at = c.last_inbound_at + s.delta,
           last_outbound_at = c.last_outbound_at + s.delta,
           first_response_at = c.first_response_at + s.delta
       FROM shift s WHERE s.id = c.id""",
    """UPDATE messages m SET created_at = m.created_at + s.delta
       FROM shift s WHERE s.id = m.conversation_id""",
    """UPDATE message_ai_results r SET created_at = r.created_at + s.delta
       FROM messages m JOIN shift s ON s.id = m.conversation_id WHERE m.id = r.message_id""",
    """UPDATE compliance_checks k SET evaluated_at = k.evaluated_at + s.delta
       FROM messages m JOIN shift s ON s.id = m.conversation_id WHERE m.id = k.message_id""",
]


async def spread(days: int) -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    try:
        async with make_sessionmaker(engine)() as session:
            await session.execute(text(_SHIFT), {"days": days})
            for statement in _APPLY:
                await session.execute(text(statement))
            moved = await session.scalar(text("SELECT count(*) FROM shift"))
            future = await session.scalar(
                text("SELECT count(*) FROM messages WHERE created_at > now() + interval '1 minute'")
            )
            if future:
                await session.rollback()
                raise SystemExit(
                    f"refusing: {future} messages would move into the future. Run `spread` only "
                    "on freshly loaded data, after the worker has drained (seed --reset, load)."
                )
            await session.commit()
        print(f"spread {moved} synthetic conversations over the last {days} days")
    finally:
        await engine.dispose()


# Children first: messages.draft_id ↔ reply_drafts is a cycle, broken by clearing it.
_PURGE = [
    """CREATE TEMP TABLE gone ON COMMIT DROP AS
       SELECT c.id FROM conversations c JOIN customers u ON u.id = c.customer_id
       WHERE u.display_name LIKE 'Load %' AND u.verified IS FALSE""",
    """DELETE FROM jobs WHERE (payload->>'conversation_id')::bigint IN (SELECT id FROM gone)
          OR (payload->>'message_id')::bigint IN
             (SELECT m.id FROM messages m WHERE m.conversation_id IN (SELECT id FROM gone))""",
    """DELETE FROM compliance_checks WHERE message_id IN
       (SELECT id FROM messages WHERE conversation_id IN (SELECT id FROM gone))""",
    "UPDATE messages SET draft_id = NULL WHERE conversation_id IN (SELECT id FROM gone)",
    "DELETE FROM reply_drafts WHERE conversation_id IN (SELECT id FROM gone)",
    "DELETE FROM conversation_summaries WHERE conversation_id IN (SELECT id FROM gone)",
    "DELETE FROM messages WHERE conversation_id IN (SELECT id FROM gone)",
    "DELETE FROM conversations WHERE id IN (SELECT id FROM gone)",
    "DELETE FROM customers WHERE display_name LIKE 'Load %' AND verified IS FALSE",
]


async def purge() -> None:
    engine = make_engine(get_settings().database_url)
    try:
        async with make_sessionmaker(engine)() as session:
            for statement in _PURGE:
                await session.execute(text(statement))
            left = await session.scalar(
                text("SELECT count(*) FROM customers WHERE display_name LIKE 'Load %'")
            )
            await session.commit()
        print(f"load-test data removed ({left} 'Load' customers left)")
    finally:
        await engine.dispose()


async def timed(client: httpx.AsyncClient, url: str, rounds: int, **kwargs) -> tuple[float, float]:
    samples = []
    for _ in range(rounds):
        started = time.perf_counter()
        r = await client.get(url, **kwargs)
        r.raise_for_status()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    return statistics.median(samples), samples[int(len(samples) * 0.95) - 1]


async def measure(api: str, rounds: int) -> None:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=api, timeout=30) as client:
        login = await client.post(
            "/api/auth/login",
            json={
                "email": "agent@unifycomm.local",
                "password": settings.seed_agent_password.get_secret_value(),
            },
        )
        login.raise_for_status()
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        inbox = (await client.get("/api/conversations", params={"limit": 50})).json()
        conversation_id = inbox["items"][0]["id"]
        counts = (await client.get("/api/metrics/summary", params={"days": 90})).json()
        print(
            f"data: {counts['conversations']} conversations (90 days), "
            f"{sum(counts['inbound_by_channel'].values())} inbound messages"
        )
        cases = [
            ("inbox (open, 50)", "/api/conversations", {"params": {"status": "open", "limit": 50}}),
            ("inbox (all, 50)", "/api/conversations", {"params": {"limit": 50}}),
            ("inbox search", "/api/conversations", {"params": {"q": "load01"}}),
            ("conversation detail", f"/api/conversations/{conversation_id}", {}),
            ("compliance log", "/api/compliance/checks", {"params": {"passed": "false"}}),
            ("metrics 7 days", "/api/metrics/summary", {"params": {"days": 7}}),
            ("metrics 90 days", "/api/metrics/summary", {"params": {"days": 90}}),
        ]
        print(f"{'endpoint':<22} {'p50 ms':>8} {'p95 ms':>8}  ({rounds} requests each)")
        for name, url, kwargs in cases:
            p50, p95 = await timed(client, url, rounds, **kwargs)
            print(f"{name:<22} {p50:>8.1f} {p95:>8.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_load = sub.add_parser("load")
    p_load.add_argument("--customers", type=int, default=150)
    p_load.add_argument("--seed", type=int, default=7)
    p_spread = sub.add_parser("spread")
    p_spread.add_argument("--days", type=int, default=7)
    sub.add_parser("purge")
    p_measure = sub.add_parser("measure")
    p_measure.add_argument("--api", default="http://localhost:8000")
    p_measure.add_argument("--rounds", type=int, default=30)
    args = parser.parse_args()
    if args.command == "load":
        asyncio.run(load(args.customers, args.seed))
    elif args.command == "spread":
        asyncio.run(spread(args.days))
    elif args.command == "purge":
        asyncio.run(purge())
    else:
        asyncio.run(measure(args.api, args.rounds))


if __name__ == "__main__":
    main()
