from app.models.job import Job


class BaseHandler:
    async def execute(self, job: Job, db_session_factory) -> dict:
        raise NotImplementedError
