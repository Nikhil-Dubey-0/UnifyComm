"""Inbound flow (ARCHITECTURE §6.1, §7.1, §7.2)."""

import asyncio

from sqlalchemy import func, select, text

from app.models import Conversation, Customer, CustomerContact, Job, Message
from tests.integration.helpers import RAHUL_EMAIL, RAHUL_PHONE, post_inbound


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_new_sender_creates_unverified_customer_and_open_conversation(client, db):
    r = await post_inbound(client, "whatsapp", "+91 90000 00001", "Hello?", sender_name="Neha")
    assert r.status_code == 201
    data = r.json()
    assert data["duplicate"] is False

    customer = await db.get(Customer, data["customer_id"])
    assert (customer.display_name, customer.verified) == ("Neha", False)
    contact = await db.scalar(select(CustomerContact))
    assert (contact.kind, contact.value_normalized, contact.verified) == (
        "phone",
        "+919000000001",
        False,
    )

    conv = await db.get(Conversation, data["conversation_id"])
    assert conv.status == "open" and conv.last_inbound_at is not None

    msg = await db.get(Message, data["message_id"])
    assert (msg.direction, msg.sender_type, msg.provider, msg.channel) == (
        "inbound",
        "customer",
        "simulator",
        "whatsapp",
    )
    assert msg.delivery_status is None
    assert msg.meta["from"] == "+919000000001" and msg.meta["sender_name"] == "Neha"

    job = await db.scalar(select(Job))
    assert (job.kind, job.payload, job.status) == (
        "analyze_message",
        {"message_id": msg.id},
        "pending",
    )


async def test_unknown_sender_without_name_uses_identifier(client, db):
    r = await post_inbound(client, "email", "  New.Person@Example.com ", "hi")
    customer = await db.get(Customer, r.json()["customer_id"])
    assert customer.display_name == "new.person@example.com"


async def test_known_sender_matches_seeded_customer(client, seeded):
    r = await post_inbound(client, "sms", "9876543210", "Hi")
    assert r.json()["customer_id"] == 1  # Rahul


async def test_cross_channel_messages_join_one_conversation(client, db, seeded):
    first = (await post_inbound(client, "whatsapp", RAHUL_PHONE, "My payment failed")).json()
    second = (
        await post_inbound(client, "email", RAHUL_EMAIL, "Any update?", subject="Payment")
    ).json()
    assert second["conversation_id"] == first["conversation_id"]
    assert await count(db, Conversation) == 1
    msg = await db.get(Message, second["message_id"])
    assert msg.meta["subject"] == "Payment"


async def test_duplicate_external_id_is_ignored(client, db):
    body = {"external_id": "wamid.ABC123"}
    first = await post_inbound(client, "whatsapp", "+91 90000 00002", "hello", **body)
    again = await post_inbound(client, "whatsapp", "+91 90000 00002", "hello", **body)
    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json() == {**first.json(), "duplicate": True}
    assert await count(db, Message) == 1
    assert await count(db, Job) == 1


async def test_same_external_id_on_another_provider_is_not_a_duplicate(client, db):
    await post_inbound(client, "whatsapp", "+91 90000 00003", "a", external_id="X1")
    await db.execute(text("UPDATE messages SET provider = 'twilio'"))
    await db.commit()
    r = await post_inbound(client, "whatsapp", "+91 90000 00003", "b", external_id="X1")
    assert r.status_code == 201 and r.json()["duplicate"] is False


async def test_resolved_conversation_is_never_reopened(client, db, seeded):
    first = (await post_inbound(client, "whatsapp", RAHUL_PHONE, "one")).json()
    await db.execute(
        text("UPDATE conversations SET status = 'resolved' WHERE id = :id"),
        {"id": first["conversation_id"]},
    )
    await db.commit()
    second = (await post_inbound(client, "whatsapp", RAHUL_PHONE, "two")).json()
    assert second["conversation_id"] != first["conversation_id"]


async def test_stale_conversation_starts_a_new_one(client, db, seeded):
    first = (await post_inbound(client, "whatsapp", RAHUL_PHONE, "one")).json()
    await db.execute(text("UPDATE conversations SET last_activity_at = now() - interval '8 days'"))
    await db.commit()
    second = (await post_inbound(client, "whatsapp", RAHUL_PHONE, "two")).json()
    assert second["conversation_id"] != first["conversation_id"]


async def test_inbound_moves_pending_conversation_back_to_open(client, db, seeded):
    first = (await post_inbound(client, "whatsapp", RAHUL_PHONE, "one")).json()
    await db.execute(text("UPDATE conversations SET status = 'pending'"))
    await db.commit()
    await post_inbound(client, "sms", RAHUL_PHONE, "two")
    conv = await db.get(Conversation, first["conversation_id"])
    await db.refresh(conv)
    assert conv.status == "open"


async def test_invalid_sender_is_rejected_with_error_envelope(client, db):
    r = await post_inbound(client, "whatsapp", "not-a-number", "hi")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_sender"
    assert await count(db, Customer) == 0


async def test_request_validation_uses_error_envelope(client):
    r = await client.post("/api/channels/simulator/inbound", json={"channel": "fax"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_concurrent_first_messages_from_new_sender(client, db):
    results = await asyncio.gather(
        *(post_inbound(client, "whatsapp", "+91 90000 00009", f"msg {i}") for i in range(5))
    )
    assert all(r.status_code == 201 for r in results)
    assert await count(db, Customer) == 1
    assert await count(db, CustomerContact) == 1
    assert await count(db, Conversation) == 1
    assert await count(db, Message) == 5
