from datetime import datetime

from app.core.queue_score import calculate_queue_score
from tests.conftest import redis


async def test_high_priority_job_scores_highest(client, redis):
    low = await client.post("/jobs", json={"type": "email", "payload": {}, "priority": 1})
    med = await client.post("/jobs", json={"type": "email", "payload": {}, "priority": 5})
    high = await client.post("/jobs", json={"type": "email", "payload": {}, "priority": 10})

    low_id = low.json()["id"]
    med_id = med.json()["id"]
    high_id = high.json()["id"]

    # zrange with rev=True returns highest score first
    results = await redis.zrevrange("jobs:queue", 0, -1, withscores=True)
    assert len(results) == 3

    member_order = [m for m, _s in results]
    assert member_order[0] == high_id
    assert member_order[1] == med_id
    assert member_order[2] == low_id


async def test_scores_match_queue_score_formula(client, redis):
    resp = await client.post("/jobs", json={"type": "email", "payload": {}, "priority": 7})
    job = resp.json()

    created_at = datetime.fromisoformat(job["created_at"])
    expected_score = calculate_queue_score(job["priority"], created_at)

    actual_score = await redis.zscore("jobs:queue", job["id"])
    assert actual_score is not None
    assert actual_score == expected_score


async def test_same_priority_fifo_ordering(client, redis):
    """Older jobs (lower created_at) should have higher scores than newer same-priority jobs."""
    first = await client.post("/jobs", json={"type": "email", "payload": {}, "priority": 5})
    second = await client.post("/jobs", json={"type": "email", "payload": {}, "priority": 5})

    first_score = await redis.zscore("jobs:queue", first.json()["id"])
    second_score = await redis.zscore("jobs:queue", second.json()["id"])

    assert first_score is not None
    assert second_score is not None
    # First submitted job has an earlier created_at → smaller subtracted ms → higher score
    assert first_score >= second_score
