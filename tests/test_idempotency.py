from sqlalchemy import func, select

from app.models.job import Job


async def test_same_idempotency_key_returns_same_job(client):
    body = {"type": "email", "payload": {}, "idempotency_key": "key-1"}

    first = await client.post("/jobs", json=body)
    second = await client.post("/jobs", json=body)

    assert first.json()["id"] == second.json()["id"]


async def test_second_call_returns_200(client):
    body = {"type": "email", "payload": {}, "idempotency_key": "key-dup"}

    first = await client.post("/jobs", json=body)
    second = await client.post("/jobs", json=body)

    assert first.status_code == 201
    assert second.status_code == 200


async def test_only_one_db_row_created(client):
    body = {"type": "email", "payload": {}, "idempotency_key": "key-unique"}
    await client.post("/jobs", json=body)
    await client.post("/jobs", json=body)
    await client.post("/jobs", json=body)

    resp = await client.get("/jobs")
    assert resp.json()["total"] == 1


async def test_different_key_creates_new_job(client):
    first = await client.post(
        "/jobs", json={"type": "email", "payload": {}, "idempotency_key": "key-a"}
    )
    second = await client.post(
        "/jobs", json={"type": "email", "payload": {}, "idempotency_key": "key-b"}
    )

    assert first.json()["id"] != second.json()["id"]
    assert second.status_code == 201
