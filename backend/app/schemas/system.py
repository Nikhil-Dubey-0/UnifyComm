from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class HealthOut(BaseModel):
    db: Literal["ok", "error"]
    worker_heartbeat_at: datetime | None
    ai_mode: Literal["fake", "real"]
    llm_configured: bool
    channels: dict[str, str]


class ComplianceRuleOut(BaseModel):
    rule_id: str
    description: str
