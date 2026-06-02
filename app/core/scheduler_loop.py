import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import update

from app.config import settings
from app.core.queue_score import calculate_queue_score
from app.database import AsyncSessionLocal
from app.models.job import Job
from app.redis_client import get_redis

logger = logging.getLogger(__name__)

JOBS_QUEUE = "jobs:queue"
JOBS_SCHEDULED = "jobs:scheduled"


async def promote_scheduled_loop(shutdown_flag: Callable[[], bool]) -> None:
    """Loop 1 — promote jobs whose run_at has passed from jobs:scheduled → jobs:queue."""
    logger.info("Scheduler loop started (promote scheduled)")

    while not shutdown_flag():
        try:
            now_ts = time.time()
            redis = get_redis()

            job_ids: list[str] = await redis.zrangebyscore(
                JOBS_SCHEDULED, 0, now_ts, start=0, num=100
            )

            for job_id_str in job_ids:
                now = datetime.now(timezone.utc)

                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        update(Job)
                        .where(
                            Job.id == job_id_str,
                            Job.status == "scheduled",
                        )
                        .values(status="pending", updated_at=now)
                        .returning(Job.id, Job.priority, Job.created_at)
                    )
                    row = result.fetchone()
                    if row is None:
                        await db.rollback()
                        continue
                    await db.commit()

                # Redis operations happen AFTER DB commit — never rollback a committed state
                try:
                    score = calculate_queue_score(row.priority, row.created_at)
                    await redis.zadd(JOBS_QUEUE, {job_id_str: score})
                    await redis.zrem(JOBS_SCHEDULED, job_id_str)
                    logger.info(
                        "Job promoted to pending",
                        extra={"job_id": job_id_str, "score": score},
                    )
                except Exception as redis_exc:
                    logger.error(
                        "Redis error after DB commit — orphan recovery will re-signal",
                        extra={"job_id": job_id_str, "error": str(redis_exc)},
                    )

        except Exception as exc:
            logger.exception(
                "Unexpected error in promote_scheduled_loop",
                extra={"error": str(exc)},
            )

        await asyncio.sleep(settings.SCHEDULER_INTERVAL_SECONDS)
