from datetime import datetime, timedelta, timezone


async def test_health_returns_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_health_reflects_pending_jobs(client):
    await client.post("/jobs", json={"type": "email", "payload": {}})
    await client.post("/jobs", json={"type": "email", "payload": {}})

    resp = await client.get("/health")
    data = resp.json()
    assert data["queue_size"] == 2
    assert data["pending_jobs"] == 2


async def test_health_reflects_scheduled_jobs(client):
    future = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()
    await client.post("/jobs", json={"type": "email", "payload": {}, "run_at": future})

    resp = await client.get("/health")
    data = resp.json()
    assert data["scheduled_size"] == 1
    assert data["queue_size"] == 0


async def test_health_has_all_required_fields(client):
    resp = await client.get("/health")
    data = resp.json()
    assert "status" in data
    assert "queue_size" in data
    assert "scheduled_size" in data
    assert "pending_jobs" in data
    assert "processing_jobs" in data
