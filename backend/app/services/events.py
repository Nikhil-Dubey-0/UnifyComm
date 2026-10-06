"""Event notifications (ARCHITECTURE §11). Emitted inside the writing transaction.

pg_notify is delivered only on commit, so a rolled-back change never produces an event.
Payloads carry IDs only; clients refetch over REST.
"""

import json
import secrets
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CHANNEL = "uc_events"


class EventType(StrEnum):
    conversation_created = "conversation.created"
    conversation_updated = "conversation.updated"
    message_created = "message.created"
    message_analyzed = "message.analyzed"
    message_status_changed = "message.status_changed"
    summary_updated = "summary.updated"


def build_event(
    type_: EventType,
    *,
    conversation_id: int | None = None,
    message_id: int | None = None,
    now: datetime | None = None,
) -> dict:
    event: dict = {"id": f"evt_{secrets.token_hex(3)}", "type": str(type_)}
    if conversation_id is not None:
        event["conversation_id"] = conversation_id
    if message_id is not None:
        event["message_id"] = message_id
    event["occurred_at"] = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return event


async def emit(
    session: AsyncSession,
    type_: EventType,
    *,
    conversation_id: int | None = None,
    message_id: int | None = None,
) -> None:
    payload = json.dumps(
        build_event(type_, conversation_id=conversation_id, message_id=message_id),
        separators=(",", ":"),
    )
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {
            "channel": CHANNEL,
            "payload": payload,
        },
    )
