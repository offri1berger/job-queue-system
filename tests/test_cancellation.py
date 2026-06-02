import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.models.job import Job


async def test_cancel_pending_job(client):
    resp = await client.post("/jobs", json={"type": "email", "payload": {}})
    job_id = resp.json()["id"]

    cancel = await client.post(f"/jobs/{job_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"


async def test_cancel_already_cancelled_returns_400(client):
    resp = await client.post("/jobs", json={"type": "email", "payload": {}})
    job_id = resp.json()["id"]

    await client.post(f"/jobs/{job_id}/cancel")
    second = await client.post(f"/jobs/{job_id}/cancel")
    assert second.status_code == 400
    assert "current state" in second.json()["detail"]


async def test_cancel_completed_job_returns_400(client, db):
    resp = await client.post("/jobs", json={"type": "email", "payload": {}})
    job_id = resp.json()["id"]

    # Directly set status=completed in DB to simulate a finished job
    await db.execute(
        update(Job).where(Job.id == uuid.UUID(job_id)).values(status="completed")
    )
    await db.commit()

    cancel = await client.post(f"/jobs/{job_id}/cancel")
    assert cancel.status_code == 400


async def test_cancel_scheduled_job(client):
    future = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()
    resp = await client.post(
        "/jobs",
        json={"type": "email", "payload": {}, "run_at": future},
    )
    job_id = resp.json()["id"]
    assert resp.json()["status"] == "scheduled"

    cancel = await client.post(f"/jobs/{job_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"


async def test_cancel_removes_from_redis_queue(client, redis):
    resp = await client.post("/jobs", json={"type": "email", "payload": {}})
    job_id = resp.json()["id"]

    # Confirm it's in the queue before cancel
    score_before = await redis.zscore("jobs:queue", job_id)
    assert score_before is not None

    await client.post(f"/jobs/{job_id}/cancel")

    # Confirm it's removed after cancel
    score_after = await redis.zscore("jobs:queue", job_id)
    assert score_after is None
