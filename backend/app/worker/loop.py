"""Worker loop: claim → handle → done, or retry with backoff (ARCHITECTURE §5.3, §12)."""

import asyncio
import logging
import os
import socket
from datetime import UTC, datetime

from app.ai.intent_map import get_intent_map
from app.channels.registry import build_registry
from app.config import Settings
from app.db import SessionMaker
from app.enums import JobKind
from app.services import jobs, system
from app.worker.classifiers import ClassifierProvider
from app.worker.handlers import HANDLERS, ON_PERMANENT_FAILURE, WorkerContext

log = logging.getLogger(__name__)

IDLE_POLL_SECONDS = 0.5
HEARTBEAT_SECONDS = 10.0


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def build_context(
    settings: Settings, sessionmaker: SessionMaker, worker_id: str | None = None
) -> WorkerContext:
    return WorkerContext(
        settings=settings,
        sessionmaker=sessionmaker,
        classifiers=ClassifierProvider(settings),
        registry=build_registry(),
        intent_map=get_intent_map(),
        worker_id=worker_id or default_worker_id(),
    )


async def process_one_job(ctx: WorkerContext) -> bool:
    """Claim and run one job. Returns False when no job was ready."""
    async with ctx.sessionmaker() as session:
        job = await jobs.claim(session, ctx.worker_id)
        await session.commit()
    if job is None:
        return False

    kind = JobKind(job.kind)
    extra = {"job_id": job.id, "kind": job.kind, "attempt": job.attempts}
    handler = HANDLERS.get(kind)
    try:
        if handler is None:
            raise LookupError(f"No handler for job kind {job.kind!r}")
        if job.attempts > job.max_attempts:
            # The lease expired after the last attempt (e.g. the worker crashed mid-job).
            raise RuntimeError("lease expired after the final attempt")
        async with ctx.sessionmaker() as session:
            await handler(ctx, session, job.payload)
            await jobs.mark_done(session, job.id)
            await session.commit()
        log.info("job done", extra=extra)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        async with ctx.sessionmaker() as session:
            permanent = await jobs.mark_failed_attempt(session, job, error)
            hook = ON_PERMANENT_FAILURE.get(kind)
            if permanent and hook is not None:
                await hook(session, job.payload, error)
            await session.commit()
        log.warning(
            "job failed permanently" if permanent else "job failed; will retry",
            extra={**extra, "error": type(exc).__name__},
            exc_info=permanent,
        )
    return True


async def heartbeat(ctx: WorkerContext) -> None:
    async with ctx.sessionmaker() as session:
        await system.put_status(
            session,
            system.HEARTBEAT_KEY,
            {
                "worker_id": ctx.worker_id,
                "ai_mode": ctx.settings.ai_mode,
                "at": datetime.now(UTC).isoformat(),
            },
        )
        await session.commit()


async def _heartbeat_forever(ctx: WorkerContext) -> None:
    while True:
        try:
            await heartbeat(ctx)
        except Exception:
            log.warning("heartbeat failed", exc_info=True)
        await asyncio.sleep(HEARTBEAT_SECONDS)


async def run_forever(ctx: WorkerContext, stop: asyncio.Event) -> None:
    log.info("worker started", extra={"worker_id": ctx.worker_id, "ai_mode": ctx.settings.ai_mode})
    beat = asyncio.create_task(_heartbeat_forever(ctx), name="heartbeat")
    if ctx.settings.ai_mode == "real":
        # Loading takes 10 s or more; start now so the first message is not delayed.
        # Jobs that arrive meanwhile wait on the provider's lock.
        preload = asyncio.create_task(asyncio.to_thread(ctx.classifiers.preload), name="preload")
    try:
        while not stop.is_set():
            try:
                worked = await process_one_job(ctx)
            except Exception:
                # Database unreachable or similar: back off and keep the worker alive.
                log.exception("worker loop error")
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=IDLE_POLL_SECONDS)
                except TimeoutError:
                    pass
    finally:
        beat.cancel()
        if ctx.settings.ai_mode == "real":
            preload.cancel()
        log.info("worker stopped", extra={"worker_id": ctx.worker_id})
