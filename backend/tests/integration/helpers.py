"""Shared helpers for integration tests."""

from typing import Any

import httpx

from app.worker.handlers import WorkerContext
from app.worker.loop import process_one_job

TEST_PASSWORD = "test-password"


async def run_all_jobs(ctx: WorkerContext, limit: int = 50) -> int:
    """Run ready jobs until the queue is empty. Returns how many ran."""
    count = 0
    while count < limit and await process_one_job(ctx):
        count += 1
    return count


async def post_inbound(
    client: httpx.AsyncClient, channel: str, sender: str, body: str, **extra: Any
):
    return await client.post(
        "/api/channels/simulator/inbound",
        json={"channel": channel, "from": sender, "body": body, **extra},
    )


RAHUL_PHONE = "+91 98765 43210"
RAHUL_EMAIL = "rahul.sharma@example.com"
PRIYA_PHONE = "+91 91234 56780"
AMIT_PHONE = "+91 99887 76655"


class FakeLLM:
    """Records requests; returns canned output or raises `error`. Tests never call OpenAI."""

    draft_model = "fake-llm-draft"
    summary_model = "fake-llm-summary"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.draft_requests: list = []
        self.summary_requests: list = []

    async def draft(self, request):
        from app.ai.llm import DraftOutput

        self.draft_requests.append(request)
        if self.error:
            raise self.error
        return DraftOutput(
            reply=f"Draft reply #{len(self.draft_requests)}",
            verify_hints=["Check the transaction status", "  "],
        )

    async def summarize(self, request):
        from app.ai.llm import SummaryOutput

        self.summary_requests.append(request)
        if self.error:
            raise self.error
        return SummaryOutput(
            summary=f"Summary #{len(self.summary_requests)}",
            customer_issue="Payment failed but money was deducted.",
            actions_taken=[],
            open_items=["Check the deduction"],
            customer_mood="frustrated",
        )
