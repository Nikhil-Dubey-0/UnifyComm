"""Seed the demo data from ARCHITECTURE §17. Idempotent; `--reset` wipes all data first.

uv run python -m scripts.seed [--reset]
"""

import argparse
import asyncio
import logging

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, setup_process
from app.db import make_engine, make_sessionmaker
from app.enums import AgentRole, Channel, Consent, ContactKind
from app.models import Agent, Base, ChannelPreference, Customer, CustomerContact
from app.services import identity
from app.services.auth import hash_password

log = logging.getLogger("seed")

AGENTS = [
    ("agent@unifycomm.local", "Demo Agent", AgentRole.agent),
    ("admin@unifycomm.local", "Demo Admin", AgentRole.admin),
]

# (name, contacts, {channel: (consent, dnd)})
CUSTOMERS = [
    (
        "Rahul Sharma",
        [(ContactKind.phone, "+91 98765 43210"), (ContactKind.email, "rahul.sharma@example.com")],
        {
            Channel.whatsapp: (Consent.opted_in, False),
            Channel.sms: (Consent.opted_in, False),
            Channel.email: (Consent.opted_in, False),
        },
    ),
    (
        "Priya Verma",
        [(ContactKind.phone, "+91 91234 56780")],
        {Channel.whatsapp: (Consent.opted_out, False), Channel.sms: (Consent.opted_in, False)},
    ),
    (
        "Amit Rao",
        [(ContactKind.phone, "+91 99887 76655")],
        {Channel.sms: (Consent.opted_in, True)},
    ),
]


async def reset(session: AsyncSession) -> None:
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


async def seed(session: AsyncSession, agent_password: str) -> None:
    for email, name, role in AGENTS:
        password_hash = hash_password(agent_password)
        await session.execute(
            insert(Agent)
            .values(email=email, name=name, role=role, password_hash=password_hash)
            .on_conflict_do_update(
                index_elements=["email"],
                set_={"name": name, "role": role, "password_hash": password_hash},
            )
        )

    for name, contacts, prefs in CUSTOMERS:
        normalized = [(kind, identity.normalize(kind, raw)) for kind, raw in contacts]
        first_kind, first_value = normalized[0]
        existing = await session.scalar(
            select(CustomerContact.customer_id).where(
                CustomerContact.kind == first_kind,
                CustomerContact.value_normalized == first_value,
            )
        )
        if existing is None:
            customer = Customer(display_name=name, verified=True)
            session.add(customer)
            await session.flush()
            customer_id = customer.id
        else:
            customer_id = existing
            customer = await session.get_one(Customer, customer_id)
            customer.display_name, customer.verified = name, True

        for kind, value in normalized:
            await session.execute(
                insert(CustomerContact)
                .values(customer_id=customer_id, kind=kind, value_normalized=value, verified=True)
                .on_conflict_do_nothing(index_elements=["kind", "value_normalized"])
            )
        for channel, (consent, dnd) in prefs.items():
            await session.execute(
                insert(ChannelPreference)
                .values(customer_id=customer_id, channel=channel, consent=consent, dnd=dnd)
                .on_conflict_do_update(
                    index_elements=["customer_id", "channel"],
                    set_={"consent": consent, "dnd": dnd},
                )
            )
        log.info("seeded customer", extra={"customer_id": customer_id, "customer": name})


async def main(do_reset: bool) -> None:
    settings = get_settings()
    setup_process(settings)
    engine = make_engine(settings.database_url)
    try:
        async with make_sessionmaker(engine)() as session:
            if do_reset:
                await reset(session)
                log.info("all tables truncated")
            await seed(session, settings.seed_agent_password.get_secret_value())
            await session.commit()
    finally:
        await engine.dispose()
    log.info("seed complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="truncate every table first")
    asyncio.run(main(parser.parse_args().reset))
