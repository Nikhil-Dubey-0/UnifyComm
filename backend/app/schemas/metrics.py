from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class DailyCount(_Model):
    date: date
    inbound: int
    outbound: int


class FirstResponse(_Model):
    count: int
    median_seconds: float | None
    p90_seconds: float | None


class DraftOutcomes(_Model):
    sent_as_is: int = 0
    edited: int = 0
    discarded: int = 0
    pending: int = 0


class CategoryCount(_Model):
    category: str | None
    queue: str
    count: int


class LabelCount(_Model):
    label: str
    count: int


class SentimentMix(_Model):
    negative: int = 0
    neutral: int = 0
    positive: int = 0


class RuleCount(_Model):
    rule_id: str
    count: int


class ComplianceMetrics(_Model):
    checked_messages: int
    blocked_messages: int
    blocks_by_rule: list[RuleCount]


class LatencyMetrics(_Model):
    task: str
    model_name: str
    count: int
    median_ms: float | None
    p90_ms: float | None


class MetricsSummary(_Model):
    days: int
    since: datetime
    conversations: int
    inbound_by_channel: dict[str, int]
    outbound_by_status: dict[str, int]
    daily: list[DailyCount]
    first_response: FirstResponse
    drafts: DraftOutcomes
    categories: list[CategoryCount]
    top_intents: list[LabelCount]
    needs_review: int
    sentiment: SentimentMix
    compliance: ComplianceMetrics
    ai_latency: list[LatencyMetrics]
