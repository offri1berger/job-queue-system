from redis.asyncio import Redis

from app.config import settings

_redis: Redis | None = None


async def connect():
    global _redis
    _redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)


async def disconnect():
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def get_redis() -> Redis:
    if _redis is None:
        raise RuntimeError("Redis not connected")
    return _redis
