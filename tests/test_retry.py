"""
Integration tests for retry/failure behaviour.

IMPORTANT: These tests require FORCE_WEBHOOK_FAIL=true in the WORKER
environment so webhook jobs always fail deterministically.

With 5 max attempts and backoff delays [0, 30, 120, 120] seconds,
a webhook job exhausting all retries takes ~275 seconds.
Set --timeout=400 or ensure pytest-timeout is installed when running.

Run:
    FORCE_WEBHOOK_FAIL=true docker-compose up --build
    docker-compose run --rm -e FORCE_WEBHOOK_FAIL=true api \\
        pytest tests/test_retry.py -v
"""
import pytest

from app.config import settings
from tests.conftest import wait_for_status

pytestmark = pytest.mark.integration

# Skip entire module when FORCE_WEBHOOK_FAIL is off to avoid false negatives
# from the 80% success rate in normal mode.
_force_fail = pytest.mark.skipif(
    not settings.FORCE_WEBHOOK_FAIL,
    reason="FORCE_WEBHOOK_FAIL not enabled — set it on both worker and test runner",
)


@_force_fail
async def test_webhook_exhausts_all_retries_then_fails(client):
    resp = await client.post(
        "/jobs",
        json={"type": "webhook", "payload": {"url": "https://example.com"}},
    )
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    # Timeout covers all backoff delays: 0 + 30 + 120 + 120 + processing slack
    job = await wait_for_status(client, job_id, "failed", timeout=400)

    max_attempts = settings.MAX_ATTEMPTS_BY_TYPE["webhook"]
    assert job["attempts"] == max_attempts
    assert job["error"] is not None
    assert job["error"] != ""


@_force_fail
async def test_retry_endpoint_resets_failed_job(client):
    resp = await client.post(
        "/jobs",
        json={"type": "webhook", "payload": {"url": "https://example.com"}},
    )
    job_id = resp.json()["id"]

    await wait_for_status(client, job_id, "failed", timeout=400)

    retry = await client.post(f"/jobs/{job_id}/retry")
    assert retry.status_code == 200
    data = retry.json()
    assert data["status"] == "pending"
    assert data["attempts"] == 0
    assert data["error"] is None
    assert data["result"] is None
