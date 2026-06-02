import asyncio
import random
from datetime import datetime, timezone
from uuid import uuid4

from app.handlers.base import BaseHandler
from app.models.job import Job


class ReportHandler(BaseHandler):
    async def execute(self, job: Job, db_session_factory) -> dict:
        await asyncio.sleep(random.uniform(3, 5))
        return {
            "file_url": f"mock://reports/{uuid4()}.pdf",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
