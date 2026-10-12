"""Customer onboarding and cross-channel identity in the simulator (user-reported bugs,
Session 5): a created sender must be saved and reusable, a customer registered with a
phone and an email gets one conversation across WhatsApp, SMS and email, and the inbox can
show the newest conversations first."""

from sqlalchemy import select, text

from app.models import AuditLog, Customer
from tests.integration.helpers import post_inbound, run_all_jobs


async def create(client, headers, **body):
    return await client.post("/api/customers", json=body, headers=headers)


async def test_new_customer_with_phone_and_email_gets_one_conversation(
    client, db, worker, agent, auth_headers, seeded
):
    r = await create(
        client,
        auth_headers,
        display_name="Ryan Kapoor",
        phone="+91 88888 88888",
        email="Ryan.Kapoor@Gmail.com",
    )
    assert r.status_code == 201, r.text
    customer = r.json()
    assert (customer["display_name"], customer["verified"]) == ("Ryan Kapoor", True)

    first = (await post_inbound(client, "whatsapp", "+91 88888 88888", "My card is blocked")).json()
    await run_all_jobs(worker)
    second = (await post_inbound(client, "email", "ryan.kapoor@gmail.com", "Any update?")).json()
    third = (await post_inbound(client, "sms", "+918888888888", "Hello?")).json()
    assert first["customer_id"] == second["customer_id"] == third["customer_id"] == customer["id"]
    assert first["conversation_id"] == second["conversation_id"] == third["conversation_id"]

    detail = (await client.get(f"/api/customers/{customer['id']}", headers=auth_headers)).json()
    assert {(c["kind"], c["value_normalized"], c["verified"]) for c in detail["contacts"]} == {
        ("phone", "+918888888888", True),
        ("email", "ryan.kapoor@gmail.com", True),
    }
    [audit] = list(await db.scalars(select(AuditLog).where(AuditLog.action == "customer.create")))
    assert (audit.actor_agent_id, audit.target_id) == (agent.id, customer["id"])


async def test_create_customer_validation(client, auth_headers, seeded):
    taken = await create(client, auth_headers, display_name="Copy", phone="+91 98765 43210")
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "contact_taken"
    assert "Rahul Sharma" in taken.json()["error"]["message"]

    assert (await create(client, auth_headers, display_name="Nobody")).status_code == 422
    bad = await create(client, auth_headers, display_name="X", phone="12")
    assert bad.status_code == 422
    blank = await create(client, auth_headers, display_name="  ", email="a@b.co")
    assert blank.status_code == 422
    assert (await client.post("/api/customers", json={"display_name": "A"})).status_code == 401


async def test_simulator_lists_new_senders_so_they_can_write_again(client, auth_headers, seeded):
    await post_inbound(client, "whatsapp", "+91 77777 00001", "hi", sender_name="Walk-in")
    contacts = (await client.get("/api/simulator/contacts", headers=auth_headers)).json()
    names = [c["display_name"] for c in contacts]
    # Verified (seeded) customers first, then recent unverified senders.
    assert names[:3] == ["Rahul Sharma", "Priya Verma", "Amit Rao"]
    walk_in = next(c for c in contacts if c["display_name"] == "Walk-in")
    assert walk_in["verified"] is False
    assert walk_in["addresses"] == {
        "whatsapp": "+917777700001",
        "sms": "+917777700001",
        "email": None,
    }


async def test_two_unverified_senders_can_be_linked(client, db, auth_headers, seeded):
    a = (await post_inbound(client, "whatsapp", "+91 77777 00002", "hi", sender_name="Ryan")).json()
    b = (
        await post_inbound(client, "email", "ryan@example.org", "hello", sender_name="Ryan")
    ).json()
    r = await client.post(
        f"/api/customers/{a['customer_id']}/link",
        json={"source_customer_id": b["customer_id"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    later = (await post_inbound(client, "email", "ryan@example.org", "still there?")).json()
    assert later["customer_id"] == a["customer_id"]


async def test_inbox_can_show_newest_first(client, db, worker, auth_headers, seeded):
    old = (await post_inbound(client, "sms", "+91 77777 00003", "refund please")).json()
    new = (await post_inbound(client, "sms", "+91 77777 00004", "refund please")).json()
    await run_all_jobs(worker)
    await db.execute(
        text(
            "UPDATE conversations SET last_activity_at = now() - interval '2 hours' WHERE id = :id"
        ),
        {"id": old["conversation_id"]},
    )
    await db.commit()

    def ids(response):
        return [i["id"] for i in response.json()["items"]]

    waiting = await client.get("/api/conversations", headers=auth_headers)
    newest = await client.get("/api/conversations", params={"sort": "newest"}, headers=auth_headers)
    assert ids(newest)[0] == new["conversation_id"]
    assert ids(newest) != ids(waiting) or len(ids(waiting)) == 1

    page1 = await client.get(
        "/api/conversations", params={"sort": "newest", "limit": 1}, headers=auth_headers
    )
    page2 = await client.get(
        "/api/conversations",
        params={"sort": "newest", "limit": 1, "cursor": page1.json()["next_cursor"]},
        headers=auth_headers,
    )
    assert ids(page1) == [new["conversation_id"]] and ids(page2) == [old["conversation_id"]]
    bad = await client.get("/api/conversations", params={"sort": "oldest"}, headers=auth_headers)
    assert bad.status_code == 422
    assert await db.scalar(select(Customer.id).where(Customer.verified.is_(False))) is not None


async def test_linking_merges_the_open_conversations(
    client, db, worker, agent, auth_headers, seeded
):
    """User bug: after a link the customer was merged but the inbox still showed two
    conversations."""
    a = (await post_inbound(client, "whatsapp", "+91 77777 00010", "My card is blocked")).json()
    b = (await post_inbound(client, "email", "ryan2@example.org", "Any update?")).json()
    await run_all_jobs(worker)
    assert a["conversation_id"] != b["conversation_id"]

    r = await client.post(
        f"/api/customers/{a['customer_id']}/link",
        json={"source_customer_id": b["customer_id"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    detail = (await client.get(f"/api/customers/{a['customer_id']}", headers=auth_headers)).json()
    assert [c["id"] for c in detail["conversations"]] == [a["conversation_id"]]
    merged = (
        await client.get(f"/api/conversations/{a['conversation_id']}", headers=auth_headers)
    ).json()
    bodies = [m["body"] for m in merged["messages"] if m["direction"] == "inbound"]
    assert bodies == ["My card is blocked", "Any update?"]
    gone = await client.get(f"/api/conversations/{b['conversation_id']}", headers=auth_headers)
    assert gone.status_code == 404
    audit = await db.scalar(select(AuditLog).where(AuditLog.action == "customer.link"))
    assert audit.details["merged_conversation_ids"] == [b["conversation_id"]]
    # The next email joins the merged conversation.
    later = (await post_inbound(client, "email", "ryan2@example.org", "Hello?")).json()
    assert later["conversation_id"] == a["conversation_id"]
