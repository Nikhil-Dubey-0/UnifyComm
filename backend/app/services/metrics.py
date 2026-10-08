"""Report metrics (ARCHITECTURE §15): GET /metrics/summary. Read-only aggregates over the
window `created_at >= now - days`; per-day counts use IST dates."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Date, case, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.intent_map import OOS_LABEL, IntentMap
from app.enums import AiStatus, AiTask, Direction
from app.models import ComplianceCheck, Conversation, Message, MessageAiResult, ReplyDraft
from app.schemas.metrics import (
    CategoryCount,
    ComplianceMetrics,
    DailyCount,
    DraftOutcomes,
    FirstResponse,
    LabelCount,
    LatencyMetrics,
    MetricsSummary,
    RuleCount,
    SentimentMix,
)

TOP_INTENTS = 10
UNCATEGORISED = "Uncategorised"


def _percentile(fraction: float, column):
    return func.percentile_cont(fraction).within_group(column)


async def summary(
    session: AsyncSession, *, days: int, intent_map: IntentMap, floor: float, timezone: str
) -> MetricsSummary:
    since = datetime.now(UTC) - timedelta(days=days)
    in_window = Message.created_at >= since

    inbound_by_channel = dict(
        (
            await session.execute(
                select(Message.channel, func.count())
                .where(in_window, Message.direction == Direction.inbound)
                .group_by(Message.channel)
            )
        ).all()
    )
    outbound_by_status = dict(
        (
            await session.execute(
                select(Message.delivery_status, func.count())
                .where(in_window, Message.direction == Direction.outbound)
                .group_by(Message.delivery_status)
            )
        ).all()
    )

    local_day = cast(func.timezone(timezone, Message.created_at), Date).label("day")
    daily = [
        DailyCount(date=row.day, inbound=row.inbound, outbound=row.outbound)
        for row in await session.execute(
            select(
                local_day,
                func.count().filter(Message.direction == Direction.inbound).label("inbound"),
                func.count().filter(Message.direction == Direction.outbound).label("outbound"),
            )
            .where(in_window)
            .group_by(local_day)
            .order_by(local_day)
        )
    ]

    conv_window = Conversation.created_at >= since
    conversations = (
        await session.scalar(select(func.count()).select_from(Conversation).where(conv_window)) or 0
    )
    response_seconds = func.extract(
        "epoch", Conversation.first_response_at - Conversation.created_at
    )
    fr = (
        await session.execute(
            select(
                func.count(),
                _percentile(0.5, response_seconds),
                _percentile(0.9, response_seconds),
            ).where(conv_window, Conversation.first_response_at.is_not(None))
        )
    ).one()

    drafts = DraftOutcomes(
        **dict(
            (
                await session.execute(
                    select(ReplyDraft.outcome, func.count())
                    .where(ReplyDraft.created_at >= since)
                    .group_by(ReplyDraft.outcome)
                )
            ).all()
        )
    )

    categories = []
    for category, count in await session.execute(
        select(Conversation.category, func.count())
        .where(conv_window)
        .group_by(Conversation.category)
        .order_by(func.count().desc())
    ):
        cat = intent_map.categories.get(category) if category else None
        queue = (cat.queue or category) if cat else UNCATEGORISED
        categories.append(CategoryCount(category=category, queue=queue, count=count))

    ai_window = (MessageAiResult.created_at >= since, MessageAiResult.status == AiStatus.ok)
    intent_rows = select(MessageAiResult.label, func.count()).where(
        *ai_window, MessageAiResult.task == AiTask.intent
    )
    top_intents = [
        LabelCount(label=label, count=count)
        for label, count in await session.execute(
            intent_rows.group_by(MessageAiResult.label)
            .order_by(func.count().desc(), MessageAiResult.label)
            .limit(TOP_INTENTS)
        )
    ]
    needs_review = (
        await session.scalar(
            select(func.count()).where(
                *ai_window,
                MessageAiResult.task == AiTask.intent,
                (MessageAiResult.label == OOS_LABEL) | (MessageAiResult.confidence < floor),
            )
        )
        or 0
    )
    sentiment = SentimentMix(
        **{
            label: count
            for label, count in await session.execute(
                select(MessageAiResult.label, func.count())
                .where(*ai_window, MessageAiResult.task == AiTask.sentiment)
                .group_by(MessageAiResult.label)
            )
            if label in SentimentMix.model_fields
        }
    )

    check_window = ComplianceCheck.evaluated_at >= since
    checked, blocked = (
        await session.execute(
            select(
                func.count(distinct(ComplianceCheck.message_id)),
                func.count(
                    distinct(case((ComplianceCheck.passed.is_(False), ComplianceCheck.message_id)))
                ),
            ).where(check_window)
        )
    ).one()
    blocks_by_rule = [
        RuleCount(rule_id=rule_id, count=count)
        for rule_id, count in await session.execute(
            select(ComplianceCheck.rule_id, func.count())
            .where(check_window, ComplianceCheck.passed.is_(False))
            .group_by(ComplianceCheck.rule_id)
            .order_by(func.count().desc(), ComplianceCheck.rule_id)
        )
    ]

    ai_latency = [
        LatencyMetrics(task=task, model_name=model, count=count, median_ms=median, p90_ms=p90)
        for task, model, count, median, p90 in await session.execute(
            select(
                MessageAiResult.task,
                MessageAiResult.model_name,
                func.count(),
                _percentile(0.5, MessageAiResult.latency_ms),
                _percentile(0.9, MessageAiResult.latency_ms),
            )
            .where(*ai_window, MessageAiResult.latency_ms.is_not(None))
            .group_by(MessageAiResult.task, MessageAiResult.model_name)
            .order_by(MessageAiResult.task)
        )
    ]

    return MetricsSummary(
        days=days,
        since=since,
        conversations=conversations,
        inbound_by_channel=inbound_by_channel,
        outbound_by_status={str(k): v for k, v in outbound_by_status.items()},
        daily=daily,
        first_response=FirstResponse(count=fr[0], median_seconds=fr[1], p90_seconds=fr[2]),
        drafts=drafts,
        categories=categories,
        top_intents=top_intents,
        needs_review=needs_review,
        sentiment=sentiment,
        compliance=ComplianceMetrics(
            checked_messages=checked, blocked_messages=blocked, blocks_by_rule=blocks_by_rule
        ),
        ai_latency=ai_latency,
    )
