import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select, update

from app.config import settings
from app.core.queue_score import calculate_queue_score
from app.database import AsyncSessionLocal
from app.models.job import Job
from app.redis_client import get_redis

logger = logging.getLogger(__name__)

JOBS_QUEUE = "jobs:queue"


async def crash_recovery_loop(shutdown_flag: Callable[[], bool]) -> None:
    """Loop 2 — recover stuck PROCESSING jobs whose locked_at is older than 10 minutes."""
    logger.info("Monitor loop started (crash recovery)")

    while not shutdown_flag():
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(
                minutes=settings.CRASH_RECOVERY_TIMEOUT_MINUTES
            )

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Job.id, Job.priority, Job.created_at)
                    .where(Job.status == "processing")
                    .where(Job.locked_at < cutoff)
                )
                stuck_jobs = result.fetchall()

            for row in stuck_jobs:
                job_id_str = str(row.id)
                now = datetime.now(timezone.utc)

                async with AsyncSessionLocal() as db:
                    update_result = await db.execute(
                        update(Job)
                        .where(Job.id == row.id, Job.status == "processing")
                        .values(
                            status="pending",
                            locked_by=None,
                            locked_at=None,
                            updated_at=now,
                        )
                        .returning(Job.id, Job.priority, Job.created_at)
                    )
                    updated = update_result.fetchone()
                    if updated is None:
                        await db.rollback()
                        continue
                    await db.commit()

                try:
                    score = calculate_queue_score(updated.priority, updated.created_at)
                    await get_redis().zadd(JOBS_QUEUE, {job_id_str: score})
                    logger.info(
                        "Stuck processing job recovered",
                        extra={"job_id": job_id_str},
                    )
                except Exception as redis_exc:
                    logger.error(
                        "Redis error in crash recovery — orphan recovery will re-signal",
                        extra={"job_id": job_id_str, "error": str(redis_exc)},
                    )

        except Exception as exc:
            logger.exception(
                "Unexpected error in crash_recovery_loop",
                extra={"error": str(exc)},
            )

        await asyncio.sleep(settings.MONITOR_INTERVAL_SECONDS)


async def orphan_recovery_loop(shutdown_flag: Callable[[], bool]) -> None:
    """Loop 3 — re-signal PENDING jobs that fell out of Redis without a status change."""
    logger.info("Monitor loop started (orphan recovery)")

    while not shutdown_flag():
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(
                minutes=settings.ORPHAN_RECOVERY_MINUTES
            )

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Job.id, Job.priority, Job.created_at)
                    .where(Job.status == "pending")
                    .where(Job.updated_at < cutoff)
                    .limit(100)
                )
                orphans = result.fetchall()

            redis = get_redis()
            for row in orphans:
                job_id_str = str(row.id)
                try:
                    score = calculate_queue_score(row.priority, row.created_at)
                    await redis.zadd(JOBS_QUEUE, {job_id_str: score})
                    logger.info(
                        "Orphan job re-signalled to Redis",
                        extra={"job_id": job_id_str},
                    )
                except Exception as redis_exc:
                    logger.error(
                        "Redis error in orphan recovery",
                        extra={"job_id": job_id_str, "error": str(redis_exc)},
                    )

        except Exception as exc:
            logger.exception(
                "Unexpected error in orphan_recovery_loop",
                extra={"error": str(exc)},
            )

        await asyncio.sleep(settings.ORPHAN_INTERVAL_SECONDS)
