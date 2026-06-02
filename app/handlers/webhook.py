import asyncio
import random
from uuid import uuid4

import httpx

from app.handlers.base import BaseHandler
from app.models.job import Job


class WebhookHandler(BaseHandler):
    async def execute(self, job: Job, db_session_factory) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:  # noqa: F841
            await asyncio.sleep(random.uniform(1, 2))
            if random.random() < 0.2:
                raise Exception("Simulated webhook failure")
            return {"webhook_id": f"mock-{uuid4()}", "status": "delivered"}
