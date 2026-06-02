from datetime import datetime, timedelta, timezone


async def test_submit_email_job_returns_201(client):
    resp = await client.post(
        "/jobs",
        json={"type": "email", "payload": {"to": "test@test.com"}},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["status"] == "pending"
    assert data["type"] == "email"
    assert data["priority"] == 0


async def test_submit_scheduled_job(client):
    future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    resp = await client.post(
        "/jobs",
        json={"type": "email", "payload": {}, "run_at": future},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "scheduled"


async def test_submit_invalid_type_returns_422(client):
    resp = await client.post(
        "/jobs",
        json={"type": "fax", "payload": {}},
    )
    assert resp.status_code == 422


async def test_get_job_by_id(client):
    create = await client.post(
        "/jobs",
        json={"type": "report", "payload": {"format": "pdf"}, "priority": 3},
    )
    job_id = create.json()["id"]

    resp = await client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == job_id
    assert data["type"] == "report"
    assert data["priority"] == 3
    assert data["payload"] == {"format": "pdf"}


async def test_get_job_not_found(client):
    resp = await client.get("/jobs/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_list_jobs_returns_list_with_total(client):
    await client.post("/jobs", json={"type": "email", "payload": {}})
    await client.post("/jobs", json={"type": "webhook", "payload": {}})

    resp = await client.get("/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert "jobs" in data
    assert "total" in data
    assert data["total"] == 2
    assert len(data["jobs"]) == 2


async def test_list_jobs_filter_by_status(client):
    future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    await client.post("/jobs", json={"type": "email", "payload": {}, "run_at": future})
    await client.post("/jobs", json={"type": "email", "payload": {}, "run_at": 
        (datetime.now(timezone.utc) + timedelta(seconds=61)).isoformat()})

    resp = await client.get("/jobs?status=scheduled")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2
