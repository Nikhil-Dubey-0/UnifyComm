"""REST surface (ARCHITECTURE §10): auth, conversations, customers, simulator, errors."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text

from app.models import Agent, AuditLog, Conversation, Customer, CustomerContact
from app.services.auth import create_token
from tests.integration.helpers import (
    AMIT_PHONE,
    PRIYA_PHONE,
    RAHUL_PHONE,
    TEST_PASSWORD,
    post_inbound,
    run_all_jobs,
)

# --- auth -------------------------------------------------------------------


async def test_login_and_me(client, seeded):
    r = await client.post(
        "/api/auth/login", json={"email": " Agent@UnifyComm.local", "password": TEST_PASSWORD}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["token_type"] == "bearer" and data["agent"]["role"] == "agent"
    me = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"}
    )
    assert me.json()["email"] == "agent@unifycomm.local"


async def test_wrong_password_and_unknown_email_look_the_same(client, seeded):
    a = await client.post(
        "/api/auth/login", json={"email": "agent@unifycomm.local", "password": "nope"}
    )
    b = await client.post("/api/auth/login", json={"email": "who@x.io", "password": "nope"})
    assert a.status_code == b.status_code == 401
    assert (
        a.json()
        == b.json()
        == {"error": {"code": "invalid_credentials", "message": "Wrong email or password."}}
    )


async def test_inactive_agent_cannot_log_in_or_use_token(client, db, agent, settings):
    token = create_token(agent.id, settings)
    agent.is_active = False
    await db.commit()
    r = await client.post("/api/auth/login", json={"email": agent.email, "password": TEST_PASSWORD})
    assert r.status_code == 401
    r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_protected_routes_need_a_valid_token(client, agent, settings):
    assert (await client.get("/api/conversations")).json()["error"]["code"] == "not_authenticated"
    expired = create_token(agent.id, settings, now=datetime.now(UTC) - timedelta(days=2))
    r = await client.get("/api/conversations", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"
    bad = await client.get("/api/conversations", headers={"Authorization": "Bearer garbage"})
    assert bad.status_code == 401


async def test_agents_lists_active_agents(client, db, auth_headers):
    admin = await db.scalar(select(Agent).where(Agent.role == "admin"))
    r = await client.get("/api/agents", headers=auth_headers)
    assert [a["name"] for a in r.json()] == ["Demo Admin", "Demo Agent"]
    admin.is_active = False
    await db.commit()
    r = await client.get("/api/agents", headers=auth_headers)
    assert [a["name"] for a in r.json()] == ["Demo Agent"]
    assert "password_hash" not in r.json()[0]
    assert (await client.get("/api/agents")).status_code == 401


async def test_unknown_route_uses_error_envelope(client):
    r = await client.get("/api/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


# --- conversations --------------------------------------------------------------


async def make_inbox(client, db, worker):
    """Amit: fraud (urgent). Rahul: payments + negative (high). Priya: cards (normal).
    New sender: needs review only (low)."""
    ids = {}
    ids["rahul"] = await post_inbound(client, "whatsapp", RAHUL_PHONE, "My payment failed")
    ids["priya"] = await post_inbound(client, "sms", PRIYA_PHONE, "When will my new card arrive?")
    ids["amit"] = await post_inbound(client, "sms", AMIT_PHONE, "My card was stolen")
    ids["new"] = await post_inbound(client, "sms", "+91 90000 00031", "hmm")
    await run_all_jobs(worker)
    return {k: v.json()["conversation_id"] for k, v in ids.items()}


async def test_inbox_order_priority_then_longest_waiting(client, db, worker, auth_headers):
    ids = await make_inbox(client, db, worker)
    items = (await client.get("/api/conversations", headers=auth_headers)).json()["items"]
    assert [i["id"] for i in items] == [ids["amit"], ids["rahul"], ids["priya"], ids["new"]]
    assert [i["priority"] for i in items] == ["urgent", "high", "normal", "low"]
    first = items[0]
    assert first["customer"] == {"id": 3, "display_name": "Amit Rao", "verified": True}
    assert first["category_queue"] == "Fraud & Security"
    assert first["last_message"]["body_preview"] == "My card was stolen"


async def test_inbox_waiting_order_within_priority(client, db, worker, auth_headers, seeded):
    a = (await post_inbound(client, "sms", "+91 90000 00041", "refund please")).json()
    b = (await post_inbound(client, "sms", "+91 90000 00042", "refund please")).json()
    await run_all_jobs(worker)
    # b has waited longer.
    await db.execute(
        text("UPDATE conversations SET last_inbound_at = now() - interval '1 hour' WHERE id = :id"),
        {"id": b["conversation_id"]},
    )
    await db.commit()
    items = (await client.get("/api/conversations", headers=auth_headers)).json()["items"]
    assert [i["id"] for i in items] == [b["conversation_id"], a["conversation_id"]]


async def test_inbox_filters(client, db, worker, agent, auth_headers):
    ids = await make_inbox(client, db, worker)

    async def ids_for(**params):
        r = await client.get("/api/conversations", params=params, headers=auth_headers)
        assert r.status_code == 200, r.text
        return [i["id"] for i in r.json()["items"]]

    assert await ids_for(category="cards") == [ids["priya"]]
    assert await ids_for(priority="urgent") == [ids["amit"]]
    assert await ids_for(q="verma") == [ids["priya"]]
    assert await ids_for(q="98765") == [ids["rahul"]]
    assert await ids_for(q="%") == []
    await client.patch(
        f"/api/conversations/{ids['rahul']}", json={"assignee_id": agent.id}, headers=auth_headers
    )
    assert await ids_for(assignee="me") == [ids["rahul"]]
    assert await ids_for(assignee=str(agent.id)) == [ids["rahul"]]
    assert ids["rahul"] not in await ids_for(assignee="unassigned")
    await client.patch(
        f"/api/conversations/{ids['amit']}", json={"status": "resolved"}, headers=auth_headers
    )
    assert await ids_for(status="resolved") == [ids["amit"]]
    bad = await client.get("/api/conversations", params={"assignee": "x"}, headers=auth_headers)
    assert bad.status_code == 422


async def test_inbox_cursor_pagination_visits_every_conversation_once(
    client, db, worker, auth_headers
):
    ids = await make_inbox(client, db, worker)
    seen, cursor = [], None
    while True:
        params = {"limit": 1, **({"cursor": cursor} if cursor else {})}
        page = (await client.get("/api/conversations", params=params, headers=auth_headers)).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [ids["amit"], ids["rahul"], ids["priya"], ids["new"]]
    bad = await client.get("/api/conversations", params={"cursor": "!!"}, headers=auth_headers)
    assert bad.status_code == 422


async def test_patch_status_transitions_and_audit(client, db, worker, agent, auth_headers):
    ids = await make_inbox(client, db, worker)
    url = f"/api/conversations/{ids['priya']}"
    r = await client.patch(url, json={"status": "resolved"}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    r = await client.patch(url, json={"status": "open"}, headers=auth_headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"
    r = await client.patch(url, json={"status": "closed"}, headers=auth_headers)
    assert r.json()["status"] == "closed"

    audit = list(await db.scalars(select(AuditLog).order_by(AuditLog.id)))
    assert [a.details["status"] for a in audit] == [["open", "resolved"], ["resolved", "closed"]]
    assert all(a.actor_agent_id == agent.id and a.action == "conversation.update" for a in audit)


async def test_patch_assignment(client, db, worker, auth_headers):
    ids = await make_inbox(client, db, worker)
    url = f"/api/conversations/{ids['priya']}"
    admin_id = await db.scalar(select(Agent.id).where(Agent.role == "admin"))
    r = await client.patch(url, json={"assignee_id": admin_id}, headers=auth_headers)
    assert r.json()["assignee_id"] == admin_id
    r = await client.patch(url, json={"assignee_id": 9999}, headers=auth_headers)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_assignee"
    r = await client.patch(url, json={"status": "pending"}, headers=auth_headers)
    assert r.json()["assignee_id"] == admin_id  # omitted field is unchanged
    r = await client.patch(url, json={"assignee_id": None}, headers=auth_headers)
    assert r.json()["assignee_id"] is None


async def test_conversation_not_found(client, auth_headers):
    r = await client.get("/api/conversations/999", headers=auth_headers)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


# --- customers ------------------------------------------------------------------


async def test_customer_list_and_detail(client, worker, auth_headers):
    await post_inbound(client, "whatsapp", RAHUL_PHONE, "hello")
    page = (await client.get("/api/customers", headers=auth_headers)).json()
    assert [c["display_name"] for c in page["items"]] == ["Rahul Sharma", "Priya Verma", "Amit Rao"]
    assert page["items"][0]["contacts"][1]["value_normalized"] == "rahul.sharma@example.com"
    assert (await client.get("/api/customers", params={"q": "amit"}, headers=auth_headers)).json()[
        "items"
    ][0]["id"] == 3
    first = (await client.get("/api/customers", params={"limit": 2}, headers=auth_headers)).json()
    assert first["next_cursor"] == "2"
    rest = (await client.get("/api/customers", params={"cursor": 2}, headers=auth_headers)).json()
    assert [c["id"] for c in rest["items"]] == [3]

    detail = (await client.get("/api/customers/1", headers=auth_headers)).json()
    assert detail["customer"]["verified"] is True
    assert {p["channel"]: p["consent"] for p in detail["preferences"]} == {
        "email": "opted_in",
        "sms": "opted_in",
        "whatsapp": "opted_in",
    }
    assert len(detail["conversations"]) == 1
    assert (await client.get("/api/customers/99", headers=auth_headers)).status_code == 404


async def test_link_unverified_sender_into_verified_customer(client, db, agent, auth_headers):
    unknown = (await post_inbound(client, "email", "rahul.personal@gmail.com", "it's Rahul")).json()
    source_id = unknown["customer_id"]
    r = await client.post(
        "/api/customers/1/link", json={"source_customer_id": source_id}, headers=auth_headers
    )
    assert r.status_code == 200 and r.json()["id"] == 1

    assert await db.get(Customer, source_id) is None
    contact = await db.scalar(
        select(CustomerContact).where(
            CustomerContact.value_normalized == "rahul.personal@gmail.com"
        )
    )
    assert contact.customer_id == 1 and contact.verified is False
    conv = await db.get(Conversation, unknown["conversation_id"])
    assert conv.customer_id == 1
    log = await db.scalar(select(AuditLog))
    assert (log.action, log.target_id, log.details["source_customer_id"]) == (
        "customer.link",
        1,
        source_id,
    )
    # The next message from that address now resolves to Rahul.
    again = (await post_inbound(client, "email", "rahul.personal@gmail.com", "hi")).json()
    assert again["customer_id"] == 1


async def test_link_refuses_verified_source_and_self(client, db, auth_headers):
    r = await client.post(
        "/api/customers/1/link", json={"source_customer_id": 2}, headers=auth_headers
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "source_verified"
    r = await client.post(
        "/api/customers/1/link", json={"source_customer_id": 1}, headers=auth_headers
    )
    assert r.status_code == 409
    r = await client.post(
        "/api/customers/1/link", json={"source_customer_id": 77}, headers=auth_headers
    )
    assert r.status_code == 404
    assert await db.scalar(select(func.count()).select_from(Customer)) == 3


# --- simulator and system ----------------------------------------------------------


async def test_simulator_contacts(client, auth_headers):
    contacts = (await client.get("/api/simulator/contacts", headers=auth_headers)).json()
    assert contacts[0] == {
        "customer_id": 1,
        "display_name": "Rahul Sharma",
        "verified": True,
        "addresses": {
            "whatsapp": "+919876543210",
            "sms": "+919876543210",
            "email": "rahul.sharma@example.com",
        },
    }
    assert contacts[1]["addresses"]["email"] is None
    assert len(contacts) == 3


async def test_simulator_thread_is_per_channel_and_address(client, auth_headers):
    await post_inbound(client, "whatsapp", RAHUL_PHONE, "on whatsapp")
    await post_inbound(client, "sms", RAHUL_PHONE, "on sms")
    r = await client.get(
        "/api/simulator/thread",
        params={"channel": "sms", "address": "9876543210"},
        headers=auth_headers,
    )
    assert [m["body"] for m in r.json()] == ["on sms"]


async def test_compliance_rules_endpoint(client, auth_headers):
    rules = (await client.get("/api/compliance/rules", headers=auth_headers)).json()
    assert [r["rule_id"] for r in rules] == [
        "consent.opt_out",
        "consent.proactive_requires_opt_in",
        "dnd.proactive",
        "time.promo_window",
        "whatsapp.session_window",
        "content.sensitive_data",
        "content.prohibited_claims",
        "content.length",
    ]
    assert all(r["description"] for r in rules)


async def test_health_without_auth(client):
    r = await client.get("/api/health")
    assert r.status_code == 200 and r.json()["db"] == "ok"
