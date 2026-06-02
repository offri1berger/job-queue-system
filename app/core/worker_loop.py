import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import update

from app.config import settings
from app.core.backoff import get_backoff_delay
from app.core.queue_score import calculate_queue_score
from app.database import AsyncSessionLocal
from app.handlers.batch import BatchHandler
from app.handlers.email import EmailHandler
from app.handlers.report import ReportHandler
from app.handlers.webhook import WebhookHandler
from app.models.job import Job
from app.redis_client import get_redis

logger = logging.getLogger(__name__)

WORKER_ID = str(uuid.uuid4())

JOBS_QUEUE = "jobs:queue"
JOBS_SCHEDULED = "jobs:scheduled"

HANDLERS = {
    "email": EmailHandler(),
    "webhook": WebhookHandler(),
    "report": ReportHandler(),
    "batch": BatchHandler(),
}


async def _claim_job(job_id: uuid.UUID) -> Job | None:
    """
    Atomic claim: UPDATE...WHERE status='pending' RETURNING *.
    fetchone() before commit — only the worker that gets a row owns the job.
    """
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "pending")
            .values(
                status="processing",
                locked_by=WORKER_ID,
                locked_at=now,
                started_at=now,
                updated_at=now,
            )
            .returning(Job)
        )
        job = result.scalars().first()
        if job is None:
            await db.rollback()
            return None
        await db.commit()
    return job


async def _complete_job(job_id: uuid.UUID, result_data: dict) -> None:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status="completed",
                result=result_data,  # Python dict — asyncpg + SQLAlchemy handle JSONB
                completed_at=now,
                locked_by=None,
                locked_at=None,
                updated_at=now,
            )
        )
        await db.commit()


async def _fail_or_retry_job(
    job_id: uuid.UUID,
    job_id_str: str,
    claimed_attempts: int,
    job_type: str,
    job_priority: int,
    job_created_at: datetime,
    exc: Exception,
) -> None:
    # CRITICAL: use claimed_attempts from the RETURNING row, not any stale object
    new_attempts = claimed_attempts + 1
    max_attempts = settings.MAX_ATTEMPTS_BY_TYPE.get(job_type, 3)
    now = datetime.now(timezone.utc)

    if new_attempts < max_attempts:
        delay = get_backoff_delay(new_attempts, settings.BACKOFF_DELAYS)

        if delay == 0:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(Job)
                    .where(Job.id == job_id)
                    .values(
                        status="pending",
                        attempts=new_attempts,
                        error=str(exc),
                        locked_by=None,
                        locked_at=None,
                        updated_at=now,
                    )
                )
                await db.commit()
            await get_redis().zadd(JOBS_QUEUE, {job_id_str: calculate_queue_score(job_priority, job_created_at)})
            logger.warning(
                "Job failed — re-queued immediately",
                extra={"job_id": job_id_str, "attempts": new_attempts},
            )
        else:
            run_at = now + timedelta(seconds=delay)
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(Job)
                    .where(Job.id == job_id)
                    .values(
                        status="scheduled",
                        attempts=new_attempts,
                        error=str(exc),
                        run_at=run_at,
                        locked_by=None,
                        locked_at=None,
                        updated_at=now,
                    )
                )
                await db.commit()
            await get_redis().zadd(JOBS_SCHEDULED, {job_id_str: run_at.timestamp()})
            logger.warning(
                "Job failed — scheduled for retry",
                extra={
                    "job_id": job_id_str,
                    "attempts": new_attempts,
                    "delay_seconds": delay,
                },
            )
    else:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    status="failed",
                    attempts=new_attempts,
                    error=str(exc),
                    locked_by=None,
                    locked_at=None,
                    updated_at=now,
                )
            )
            await db.commit()
        logger.error(
            "Job permanently failed",
            extra={"job_id": job_id_str, "attempts": new_attempts, "error": str(exc)},
        )


async def process_one(job_id_str: str) -> None:
    job_id = uuid.UUID(job_id_str)

    job = await _claim_job(job_id)
    if job is None:
        logger.info("Job not claimable — skipping", extra={"job_id": job_id_str})
        return

    # Save attempts from the atomic claim row before any handler runs
    claimed_attempts = job.attempts
    logger.info(
        "Job claimed",
        extra={"job_id": job_id_str, "type": job.type, "worker_id": WORKER_ID},
    )

    handler = HANDLERS.get(job.type)
    if handler is None:
        logger.error(
            "Unknown job type — failing permanently",
            extra={"job_id": job_id_str, "type": job.type},
        )
        await _fail_or_retry_job(
            job_id,
            job_id_str,
            claimed_attempts,
            job.type,
            job.priority,
            job.created_at,
            ValueError(f"Unknown job type: {job.type}"),
        )
        return

    try:
        result_data = await handler.execute(job, AsyncSessionLocal)
        await _complete_job(job_id, result_data)
        logger.info("Job completed", extra={"job_id": job_id_str, "type": job.type})
    except Exception as exc:
        logger.warning(
            "Job execution failed",
            extra={"job_id": job_id_str, "type": job.type, "error": str(exc)},
        )
        await _fail_or_retry_job(
            job_id, job_id_str, claimed_attempts, job.type, job.priority, job.created_at, exc
        )


async def worker_loop(shutdown_flag: Callable[[], bool]) -> None:
    logger.info("Worker loop started", extra={"worker_id": WORKER_ID})
    redis = get_redis()

    while not shutdown_flag():
        try:
            items = await redis.zpopmax(JOBS_QUEUE, 1)
            if not items:
                await asyncio.sleep(0.5)
                continue

            job_id_str, _score = items[0]
            logger.info("Job popped from queue", extra={"job_id": job_id_str})
            await process_one(job_id_str)

        except Exception as exc:
            logger.exception(
                "Unexpected error in worker loop", extra={"error": str(exc)}
            )
            await asyncio.sleep(1)

    logger.info("Worker loop exiting", extra={"worker_id": WORKER_ID})
