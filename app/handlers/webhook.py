import asyncio
import random
from uuid import uuid4

import httpx

from app.config import settings
from app.handlers.base import BaseHandler
from app.models.job import Job


class WebhookHandler(BaseHandler):
    async def execute(self, job: Job, db_session_factory) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:  # noqa: F841
            await asyncio.sleep(random.uniform(1, 2))
            if settings.FORCE_WEBHOOK_FAIL or random.random() < 0.2:
                raise Exception("Simulated webhook failure")
            return {"webhook_id": f"mock-{uuid4()}", "status": "delivered"}
