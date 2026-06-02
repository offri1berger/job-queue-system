from datetime import datetime, timedelta, timezone


async def test_scheduled_job_status_is_scheduled(client):
    future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    resp = await client.post(
        "/jobs",
        json={"type": "email", "payload": {}, "run_at": future},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "scheduled"


async def test_scheduled_job_in_jobs_scheduled_sorted_set(client, redis):
    future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    resp = await client.post(
        "/jobs",
        json={"type": "email", "payload": {}, "run_at": future},
    )
    job_id = resp.json()["id"]

    score = await redis.zscore("jobs:scheduled", job_id)
    assert score is not None


async def test_scheduled_job_not_in_jobs_queue(client, redis):
    future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    resp = await client.post(
        "/jobs",
        json={"type": "email", "payload": {}, "run_at": future},
    )
    job_id = resp.json()["id"]

    queue_score = await redis.zscore("jobs:queue", job_id)
    assert queue_score is None


async def test_scheduled_score_matches_run_at_timestamp(client, redis):
    future_dt = datetime.now(timezone.utc) + timedelta(seconds=60)
    resp = await client.post(
        "/jobs",
        json={"type": "email", "payload": {}, "run_at": future_dt.isoformat()},
    )
    job_id = resp.json()["id"]
    run_at_from_response = datetime.fromisoformat(resp.json()["run_at"])

    score = await redis.zscore("jobs:scheduled", job_id)
    assert score is not None
    # Score should be within 1 second of the run_at timestamp
    assert abs(score - run_at_from_response.timestamp()) < 1.0
