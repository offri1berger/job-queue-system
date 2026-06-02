from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://jobqueue:jobqueue@localhost:5432/jobqueue"
    REDIS_URL: str = "redis://localhost:6379"

    WORKER_CONCURRENCY: int = 1
    LOG_LEVEL: str = "INFO"

    MAX_ATTEMPTS_BY_TYPE: dict = {
        "email": 3,
        "webhook": 5,
        "report": 1,
        "batch": 3,
    }
    BACKOFF_DELAYS: list = [0, 30, 120]

    CRASH_RECOVERY_TIMEOUT_MINUTES: int = 10
    ORPHAN_RECOVERY_MINUTES: int = 2

    SCHEDULER_INTERVAL_SECONDS: int = 5
    MONITOR_INTERVAL_SECONDS: int = 60
    ORPHAN_INTERVAL_SECONDS: int = 300

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
