from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobType(str, Enum):
    email = "email"
    webhook = "webhook"
    report = "report"
    batch = "batch"


class JobStatus(str, Enum):
    scheduled = "scheduled"
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class JobCreate(BaseModel):
    type: JobType
    payload: dict
    priority: int = 0
    idempotency_key: Optional[str] = None
    run_at: Optional[datetime] = None


class JobResponse(BaseModel):
    id: UUID
    type: str
    status: str
    payload: dict
    result: Optional[dict] = None
    priority: int
    attempts: int
    progress: int
    error: Optional[str] = None
    run_at: Optional[datetime] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobListResponse(BaseModel):
    jobs: List[JobResponse]
    total: int


class HealthResponse(BaseModel):
    status: str
    queue_size: int
    scheduled_size: int
    pending_jobs: int
    processing_jobs: int
