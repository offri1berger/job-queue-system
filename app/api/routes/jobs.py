import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.queue_score import calculate_queue_score
from app.database import get_db
from app.models.job import Job
from app.redis_client import get_redis
from app.schemas.job import JobCreate, JobListResponse, JobResponse

router = APIRouter()

JOBS_QUEUE = "jobs:queue"
JOBS_SCHEDULED = "jobs:scheduled"


@router.post("/jobs", status_code=201, response_model=JobResponse)
async def create_job(
    body: JobCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    try:
        if body.idempotency_key:
            result = await db.execute(
                select(Job).where(Job.idempotency_key == body.idempotency_key)
            )
            existing = result.scalar_one_or_none()
            if existing:
                response.status_code = 200
                return JobResponse.model_validate(existing)

        now = datetime.now(timezone.utc)
        run_at = body.run_at
        if run_at is not None and run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=timezone.utc)

        status = "scheduled" if (run_at and run_at > now) else "pending"

        job = Job(
            type=body.type.value,
            status=status,
            payload=body.payload,
            priority=body.priority,
            idempotency_key=body.idempotency_key,
            run_at=run_at,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        job_id_str = str(job.id)
        if status == "pending":
            await redis.zadd(JOBS_QUEUE, {job_id_str: calculate_queue_score(job.priority, job.created_at)})
        else:
            await redis.zadd(JOBS_SCHEDULED, {job_id_str: run_at.timestamp()})

        return JobResponse.model_validate(job)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    status: Optional[str] = Query(default=None),
    job_type: Optional[str] = Query(default=None, alias="type"),
    priority: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    try:
        query = select(Job)
        count_query = select(func.count(Job.id))

        if status is not None:
            query = query.where(Job.status == status)
            count_query = count_query.where(Job.status == status)
        if job_type is not None:
            query = query.where(Job.type == job_type)
            count_query = count_query.where(Job.type == job_type)
        if priority is not None:
            query = query.where(Job.priority == priority)
            count_query = count_query.where(Job.priority == priority)

        query = query.order_by(Job.created_at.desc()).limit(50)

        jobs_result = await db.execute(query)
        jobs = jobs_result.scalars().all()

        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

        return JobListResponse(
            jobs=[JobResponse.model_validate(j) for j in jobs],
            total=total,
        )

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return JobResponse.model_validate(job)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    try:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        if job.status not in ("pending", "scheduled"):
            raise HTTPException(
                status_code=400,
                detail="Job cannot be cancelled in its current state",
            )

        job.status = "cancelled"
        job.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(job)

        job_id_str = str(job.id)
        await redis.zrem(JOBS_QUEUE, job_id_str)
        await redis.zrem(JOBS_SCHEDULED, job_id_str)

        return JobResponse.model_validate(job)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
async def retry_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    try:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        if job.status != "failed":
            raise HTTPException(
                status_code=400,
                detail="Only failed jobs can be retried",
            )

        job.status = "pending"
        job.attempts = 0
        job.error = None
        job.result = None
        job.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(job)

        await redis.zadd(JOBS_QUEUE, {str(job.id): calculate_queue_score(job.priority, job.created_at)})

        return JobResponse.model_validate(job)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/health")
async def health(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    try:
        queue_size = await redis.zcard(JOBS_QUEUE)
        scheduled_size = await redis.zcard(JOBS_SCHEDULED)

        pending_result = await db.execute(
            select(func.count(Job.id)).where(Job.status == "pending")
        )
        pending_jobs = pending_result.scalar() or 0

        processing_result = await db.execute(
            select(func.count(Job.id)).where(Job.status == "processing")
        )
        processing_jobs = processing_result.scalar() or 0

        return {
            "status": "ok",
            "queue_size": queue_size,
            "scheduled_size": scheduled_size,
            "pending_jobs": pending_jobs,
            "processing_jobs": processing_jobs,
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
