"""Seed the demo data from ARCHITECTURE §17. Idempotent; `--reset` wipes all data first.

uv run python -m scripts.seed [--reset]
"""

import argparse
import asyncio
import logging

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings, setup_process
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


def test_contact(settings: Settings) -> tuple | None:
    """The user's own phone and email (TEST_CONTACT_* in .env) as one verified customer, so
    a real WhatsApp message and a real email from them meet in one conversation (§17)."""
    contacts = []
    if settings.test_contact_phone.strip():
        contacts.append((ContactKind.phone, settings.test_contact_phone.strip()))
    if settings.test_contact_email.strip():
        contacts.append((ContactKind.email, settings.test_contact_email.strip()))
    if not contacts:
        return None
    opted_in = (Consent.opted_in, False)
    return (
        settings.test_contact_name.strip() or "Test Contact",
        contacts,
        {Channel.whatsapp: opted_in, Channel.sms: opted_in, Channel.email: opted_in},
    )


async def seed(session: AsyncSession, agent_password: str, extra: list[tuple] = ()) -> None:
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

    for index, (name, contacts, prefs) in enumerate([*CUSTOMERS, *extra]):
        move_contacts = index >= len(CUSTOMERS)
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
            stmt = insert(CustomerContact).values(
                customer_id=customer_id, kind=kind, value_normalized=value, verified=True
            )
            if move_contacts:
                # The user may have written in before seeding: claim the address so phone
                # and email belong to one customer (§17 test contact).
                stmt = stmt.on_conflict_do_update(
                    index_elements=["kind", "value_normalized"],
                    set_={"customer_id": customer_id, "verified": True},
                )
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=["kind", "value_normalized"])
            await session.execute(stmt)
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
            contact = test_contact(settings)
            await seed(
                session,
                settings.seed_agent_password.get_secret_value(),
                [contact] if contact else [],
            )
            await session.commit()
    finally:
        await engine.dispose()
    log.info("seed complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="truncate every table first")
    asyncio.run(main(parser.parse_args().reset))
