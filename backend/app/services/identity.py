"""Identity resolution (ARCHITECTURE §7.1): exact, normalized identifiers only."""

import re
from dataclasses import dataclass

import phonenumbers
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ContactKind
from app.errors import Unprocessable
from app.models import Customer, CustomerContact

DEFAULT_REGION = "IN"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InvalidIdentifier(Unprocessable):
    code = "invalid_sender"


def normalize_phone(raw: str) -> str:
    value = raw.strip()
    if value.lower().startswith("whatsapp:"):
        value = value[len("whatsapp:") :]
    try:
        parsed = phonenumbers.parse(value, DEFAULT_REGION)
    except phonenumbers.NumberParseException as exc:
        raise InvalidIdentifier(f"Not a phone number: {raw!r}") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise InvalidIdentifier(f"Not a valid phone number: {raw!r}")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def normalize_email(raw: str) -> str:
    value = raw.strip().lower()
    if not _EMAIL.match(value):
        raise InvalidIdentifier(f"Not a valid email address: {raw!r}")
    return value


def normalize(kind: ContactKind, raw: str) -> str:
    return normalize_phone(raw) if kind is ContactKind.phone else normalize_email(raw)


@dataclass(frozen=True)
class ResolvedSender:
    customer_id: int
    contact_id: int
    created: bool


async def resolve(
    session: AsyncSession, kind: ContactKind, value: str, display_name: str | None
) -> ResolvedSender:
    """Find the customer that owns (kind, value), or create an unverified one.

    `value` must already be normalized. Concurrent first messages from one new sender are
    safe: the contact insert uses ON CONFLICT, and the loser drops its customer row.
    """
    found = await _find_contact(session, kind, value)
    if found:
        return ResolvedSender(customer_id=found.customer_id, contact_id=found.id, created=False)

    customer = Customer(display_name=(display_name or "").strip() or value, verified=False)
    session.add(customer)
    await session.flush()
    contact_id = await session.scalar(
        insert(CustomerContact)
        .values(customer_id=customer.id, kind=kind, value_normalized=value, verified=False)
        .on_conflict_do_nothing(index_elements=["kind", "value_normalized"])
        .returning(CustomerContact.id)
    )
    if contact_id is not None:
        return ResolvedSender(customer_id=customer.id, contact_id=contact_id, created=True)

    # Another transaction registered this sender first; use theirs.
    await session.execute(delete(Customer).where(Customer.id == customer.id))
    found = await _find_contact(session, kind, value)
    if found is None:  # pragma: no cover - the conflicting row must exist
        raise RuntimeError("contact vanished after conflict")
    return ResolvedSender(customer_id=found.customer_id, contact_id=found.id, created=False)


async def _find_contact(
    session: AsyncSession, kind: ContactKind, value: str
) -> CustomerContact | None:
    return await session.scalar(
        select(CustomerContact).where(
            CustomerContact.kind == kind, CustomerContact.value_normalized == value
        )
    )
