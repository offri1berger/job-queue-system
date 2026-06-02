import asyncio
import random
from uuid import uuid4

from app.handlers.base import BaseHandler
from app.models.job import Job


class EmailHandler(BaseHandler):
    async def execute(self, job: Job, db_session_factory) -> dict:
        await asyncio.sleep(random.uniform(1, 3))
        return {"message_id": f"mock-{uuid4()}"}
