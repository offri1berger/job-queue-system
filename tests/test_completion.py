import pytest

from tests.conftest import wait_for_status

pytestmark = pytest.mark.integration


async def test_email_job_completes(client):
    resp = await client.post(
        "/jobs",
        json={"type": "email", "payload": {"to": "test@test.com"}},
    )
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    job = await wait_for_status(client, job_id, "completed", timeout=30)

    assert job["status"] == "completed"
    assert job["result"] is not None
    assert "message_id" in job["result"]
    assert job["started_at"] is not None
    assert job["completed_at"] is not None
    assert job["attempts"] == 0


async def test_report_job_completes_with_file_url(client):
    resp = await client.post(
        "/jobs",
        json={"type": "report", "payload": {"format": "pdf"}},
    )
    job_id = resp.json()["id"]

    job = await wait_for_status(client, job_id, "completed", timeout=30)

    assert "file_url" in job["result"]
    assert "generated_at" in job["result"]


async def test_batch_job_tracks_progress(client):
    items = list(range(10))
    resp = await client.post(
        "/jobs",
        json={"type": "batch", "payload": {"items": items}},
    )
    job_id = resp.json()["id"]

    job = await wait_for_status(client, job_id, "completed", timeout=30)

    assert job["result"]["processed"] == 10
    assert job["progress"] == 100
