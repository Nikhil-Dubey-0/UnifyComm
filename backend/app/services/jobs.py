"""Postgres job queue (ARCHITECTURE D4, §12): SKIP LOCKED claims, leases, retries."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import JobKind, JobStatus
from app.models import Job

LEASE = timedelta(minutes=5)
BACKOFF_BASE_SECONDS = 5
LAST_ERROR_MAX_CHARS = 2000

_CLAIM_SQL = text(
    """
    UPDATE jobs SET status = 'running', locked_at = now(), locked_by = :worker,
                    attempts = attempts + 1, updated_at = now()
    WHERE id = (
      SELECT id FROM jobs
      WHERE (status = 'pending' AND run_after <= now())
         OR (status = 'running' AND locked_at < now() - make_interval(secs => :lease_seconds))
      ORDER BY run_after, id
      FOR UPDATE SKIP LOCKED
      LIMIT 1)
    RETURNING id
    """
)


async def enqueue(
    session: AsyncSession,
    kind: JobKind,
    payload: dict[str, Any],
    *,
    run_after: datetime | None = None,
    max_attempts: int = 3,
) -> int:
    job = Job(kind=kind, payload=payload, max_attempts=max_attempts)
    if run_after is not None:
        job.run_after = run_after
    session.add(job)
    await session.flush()
    return job.id


async def enqueue_summary(session: AsyncSession, conversation_id: int) -> int:
    """Queue `summarize_conversation` unless one is already pending or running for this
    conversation (partial unique index uq_jobs_active_summary). Returns the job id."""
    while True:
        job_id = await session.scalar(
            insert(Job)
            .values(
                kind=JobKind.summarize_conversation, payload={"conversation_id": conversation_id}
            )
            .on_conflict_do_nothing()
            .returning(Job.id)
        )
        if job_id is None:
            job_id = await session.scalar(
                select(Job.id).where(
                    Job.kind == JobKind.summarize_conversation,
                    Job.payload["conversation_id"].as_integer() == conversation_id,
                    Job.status.in_([JobStatus.pending, JobStatus.running]),
                )
            )
        # None only if the active job finished between the two statements: insert again.
        if job_id is not None:
            return job_id


async def claim(session: AsyncSession, worker_id: str) -> Job | None:
    job_id = await session.scalar(
        _CLAIM_SQL, {"worker": worker_id, "lease_seconds": LEASE.total_seconds()}
    )
    if job_id is None:
        return None
    return await session.scalar(
        select(Job).where(Job.id == job_id).execution_options(populate_existing=True)
    )


def retry_delay(attempts: int) -> timedelta:
    """5 s × 2^attempts (ARCHITECTURE §5.3)."""
    return timedelta(seconds=BACKOFF_BASE_SECONDS * 2**attempts)


async def mark_done(session: AsyncSession, job_id: int) -> None:
    await session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(status=JobStatus.done, locked_at=None, locked_by=None, last_error=None)
    )


async def mark_failed_attempt(
    session: AsyncSession, job: Job, error: str, *, now: datetime | None = None
) -> bool:
    """Record a failed attempt. Returns True if the job is now permanently failed."""
    now = now or datetime.now(UTC)
    permanent = job.attempts >= job.max_attempts
    values: dict[str, Any] = {
        "locked_at": None,
        "locked_by": None,
        "last_error": error[:LAST_ERROR_MAX_CHARS],
    }
    if permanent:
        values["status"] = JobStatus.failed
    else:
        values["status"] = JobStatus.pending
        values["run_after"] = now + retry_delay(job.attempts)
    await session.execute(update(Job).where(Job.id == job.id).values(**values))
    return permanent
