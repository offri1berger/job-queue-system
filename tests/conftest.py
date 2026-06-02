import asyncio
import asyncpg
import httpx
import pytest
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.database import AsyncSessionLocal

BASE_URL = "http://api:8000"

@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as c:
        yield c

@pytest.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session

@pytest.fixture
async def redis():
    r = aioredis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    yield r
    await r.aclose()

@pytest.fixture(autouse=True)
async def clean_state():
    db_url = settings.DATABASE_URL.replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    conn = await asyncpg.connect(db_url)
    await conn.execute(
        "TRUNCATE TABLE job_logs, jobs RESTART IDENTITY CASCADE"
    )
    await conn.close()

    r = aioredis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    await r.flushdb()
    await r.aclose()
    yield

async def wait_for_status(
    client: httpx.AsyncClient,
    job_id: str,
    target_status: str,
    timeout: int = 30
) -> dict:
    for _ in range(timeout):
        r = await client.get(f"/jobs/{job_id}")
        if r.json()["status"] == target_status:
            return r.json()
        await asyncio.sleep(1)
    raise TimeoutError(
        f"Job {job_id} never reached {target_status} within {timeout}s"
    )