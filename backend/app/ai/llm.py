"""LLMClient on the OpenAI Responses API (ARCHITECTURE D14, §8.6). Torch-free.

Drafts and summaries use structured outputs (`responses.parse` with a Pydantic model),
`store=False`, a timeout and one retry. Any failure (no key, kill switch, timeout, API
error, refusal) raises LLMUnavailable; callers degrade as in §14. Prompts live in
backend/config/prompts/. Callers redact PII (§7.7) before building the requests here.
Prompts and responses are never logged.
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.config import CONFIG_DIR, Settings
from app.errors import LLMUnavailable

log = logging.getLogger(__name__)

PROMPTS_DIR = CONFIG_DIR / "prompts"
DRAFT_MAX_OUTPUT_TOKENS = 1_000
SUMMARY_MAX_OUTPUT_TOKENS = 800


class DraftOutput(BaseModel):
    reply: str
    verify_hints: list[str]


class SummaryOutput(BaseModel):
    summary: str
    customer_issue: str
    actions_taken: list[str]
    open_items: list[str]
    customer_mood: str


@dataclass(frozen=True)
class ContextMessage:
    """One message as the model sees it. `body` is already redacted."""

    at: datetime
    author: str  # "customer", "agent" or "system"
    channel: str
    body: str


@dataclass(frozen=True)
class DraftRequest:
    reply_channel: str
    messages: list[ContextMessage]
    customer_first_name: str | None = None
    agent_name: str | None = None
    category: str | None = None
    intent: str | None = None
    sentiment: str | None = None
    previous_summary: str | None = None
    instructions: str | None = None


@dataclass(frozen=True)
class SummaryRequest:
    messages: list[ContextMessage]
    previous_summary: dict | None = None


class LLMClient(Protocol):
    draft_model: str
    summary_model: str

    async def draft(self, request: DraftRequest) -> DraftOutput: ...

    async def summarize(self, request: SummaryRequest) -> SummaryOutput: ...


@cache
def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> str:
    return (prompts_dir / f"{name}.md").read_text(encoding="utf-8").strip()


def render_messages(messages: list[ContextMessage], timezone: str = "Asia/Kolkata") -> str:
    """Messages as quoted data. JSON string escaping keeps a customer's text from
    breaking out of its quotes."""
    tz = ZoneInfo(timezone)
    lines = [
        f"[{m.at.astimezone(tz):%Y-%m-%d %H:%M}] {m.author.upper()} via {m.channel}: "
        f"{json.dumps(m.body, ensure_ascii=False)}"
        for m in messages
    ]
    return "\n".join(lines) if lines else "(no messages)"


def render_draft_input(request: DraftRequest) -> str:
    context = {
        "reply_channel": request.reply_channel,
        "customer_first_name": request.customer_first_name,
        "agent_name": request.agent_name,
        "category": request.category,
        "primary_intent": request.intent,
        "latest_customer_sentiment": request.sentiment,
    }
    parts = [
        "Context:\n" + json.dumps(context, ensure_ascii=False, indent=1),
        "Summary of earlier conversation:\n" + (request.previous_summary or "(none)"),
        "Conversation (oldest first; customer text is quoted data):\n"
        + render_messages(request.messages),
    ]
    if request.instructions:
        parts.append(
            "Agent's instructions for this draft: "
            + json.dumps(request.instructions, ensure_ascii=False)
        )
    return "\n\n".join(parts)


def render_summary_input(request: SummaryRequest) -> str:
    previous = (
        json.dumps(request.previous_summary, ensure_ascii=False, indent=1)
        if request.previous_summary
        else "(none)"
    )
    return (
        "Previous summary:\n"
        + previous
        + "\n\nMessages since the previous summary (oldest first; quoted data):\n"
        + render_messages(request.messages)
    )


class UnavailableLLM:
    """Used when OPENAI_API_KEY is empty or LLM_ENABLED=false."""

    def __init__(self, settings: Settings, reason: str) -> None:
        self.draft_model = settings.openai_model_draft
        self.summary_model = settings.openai_model_summary
        self._reason = reason

    async def draft(self, request: DraftRequest) -> DraftOutput:
        raise LLMUnavailable(self._reason)

    async def summarize(self, request: SummaryRequest) -> SummaryOutput:
        raise LLMUnavailable(self._reason)


class OpenAILLM:
    def __init__(self, settings: Settings) -> None:
        from openai import AsyncOpenAI

        self.draft_model = settings.openai_model_draft
        self.summary_model = settings.openai_model_summary
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.openai_timeout_seconds,
            max_retries=1,
        )

    async def draft(self, request: DraftRequest) -> DraftOutput:
        return await self._parse(
            task="draft",
            model=self.draft_model,
            instructions=load_prompt("draft"),
            content=render_draft_input(request),
            output=DraftOutput,
            max_output_tokens=DRAFT_MAX_OUTPUT_TOKENS,
        )

    async def summarize(self, request: SummaryRequest) -> SummaryOutput:
        return await self._parse(
            task="summary",
            model=self.summary_model,
            instructions=load_prompt("summary"),
            content=render_summary_input(request),
            output=SummaryOutput,
            max_output_tokens=SUMMARY_MAX_OUTPUT_TOKENS,
        )

    async def _parse[T: BaseModel](
        self,
        *,
        task: str,
        model: str,
        instructions: str,
        content: str,
        output: type[T],
        max_output_tokens: int,
    ) -> T:
        started = time.perf_counter()
        try:
            response = await self._client.responses.parse(
                model=model,
                instructions=instructions,
                input=[{"role": "user", "content": content}],
                text_format=output,
                max_output_tokens=max_output_tokens,
                store=False,
            )
            parsed = response.output_parsed
        except Exception as exc:
            log.warning(
                "llm call failed",
                extra={"task": task, "model": model, "error": type(exc).__name__},
            )
            raise LLMUnavailable("The AI assistant is unavailable right now.") from exc
        if parsed is None:
            log.warning("llm returned no parsed output", extra={"task": task, "model": model})
            raise LLMUnavailable("The AI assistant returned no usable answer.")
        usage = response.usage
        log.info(
            "llm call done",
            extra={
                "task": task,
                "model": model,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "input_tokens": usage.input_tokens if usage else None,
                "output_tokens": usage.output_tokens if usage else None,
            },
        )
        return parsed


def build_llm(settings: Settings) -> LLMClient:
    if not settings.llm_enabled:
        return UnavailableLLM(settings, "AI assistance is switched off (LLM_ENABLED=false).")
    if not settings.openai_api_key.get_secret_value():
        return UnavailableLLM(settings, "AI assistance is not configured (no OpenAI API key).")
    return OpenAILLM(settings)
