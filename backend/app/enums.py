"""Enum-like values shared by the ORM (CHECK constraints), schemas and services."""

from enum import StrEnum


class Channel(StrEnum):
    whatsapp = "whatsapp"
    sms = "sms"
    email = "email"


class Provider(StrEnum):
    simulator = "simulator"
    twilio = "twilio"
    gmail = "gmail"


class ContactKind(StrEnum):
    phone = "phone"
    email = "email"


class AgentRole(StrEnum):
    agent = "agent"
    admin = "admin"


class Consent(StrEnum):
    opted_in = "opted_in"
    opted_out = "opted_out"
    unknown = "unknown"


class ConversationStatus(StrEnum):
    open = "open"
    pending = "pending"
    resolved = "resolved"
    closed = "closed"


class Priority(StrEnum):
    urgent = "urgent"
    high = "high"
    normal = "normal"
    low = "low"


class Direction(StrEnum):
    inbound = "inbound"
    outbound = "outbound"


class SenderType(StrEnum):
    customer = "customer"
    agent = "agent"
    system = "system"


class Purpose(StrEnum):
    service_reply = "service_reply"
    proactive = "proactive"


class DeliveryStatus(StrEnum):
    checking = "checking"
    blocked = "blocked"
    queued = "queued"
    sent = "sent"
    delivered = "delivered"
    failed = "failed"


class AiTask(StrEnum):
    intent = "intent"
    sentiment = "sentiment"


class AiStatus(StrEnum):
    ok = "ok"
    error = "error"


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class JobKind(StrEnum):
    analyze_message = "analyze_message"
    summarize_conversation = "summarize_conversation"
    deliver_message = "deliver_message"
    send_acknowledgement = "send_acknowledgement"


class DraftOutcome(StrEnum):
    pending = "pending"
    sent_as_is = "sent_as_is"
    edited = "edited"
    discarded = "discarded"


CONTACT_KIND_FOR_CHANNEL: dict[Channel, ContactKind] = {
    Channel.whatsapp: ContactKind.phone,
    Channel.sms: ContactKind.phone,
    Channel.email: ContactKind.email,
}
