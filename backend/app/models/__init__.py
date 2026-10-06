"""ORM models. Importing this package registers every table on Base.metadata."""

from app.models.agent import Agent
from app.models.base import Base
from app.models.conversation import Conversation, ConversationSummary, ReplyDraft
from app.models.customer import ChannelPreference, Customer, CustomerContact
from app.models.message import ComplianceCheck, Message, MessageAiResult
from app.models.system import AuditLog, Job, SystemStatus

__all__ = [
    "Agent",
    "AuditLog",
    "Base",
    "ChannelPreference",
    "ComplianceCheck",
    "Conversation",
    "ConversationSummary",
    "Customer",
    "CustomerContact",
    "Job",
    "Message",
    "MessageAiResult",
    "ReplyDraft",
    "SystemStatus",
]
