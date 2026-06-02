import asyncio

from sqlalchemy import update

from app.handlers.base import BaseHandler
from app.models.job import Job


class BatchHandler(BaseHandler):
    async def execute(self, job: Job, db_session_factory) -> dict:
        items = job.payload.get("items", [])
        total = len(items)

        if total == 0:
            return {"processed": 0, "summary": "Processed 0 items successfully"}

        last_reported_progress = -1

        for i in range(total):
            await asyncio.sleep(0.5)
            progress = int((i + 1) / total * 100)

            if progress % 10 == 0 and progress != last_reported_progress:
                last_reported_progress = progress
                async with db_session_factory() as db:
                    await db.execute(
                        update(Job)
                        .where(Job.id == job.id)
                        .values(progress=progress)
                    )
                    await db.commit()

        return {"processed": total, "summary": f"Processed {total} items successfully"}
