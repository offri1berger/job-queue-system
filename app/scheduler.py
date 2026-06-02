import asyncio
import json
import logging
import signal

from app.config import settings
from app.core.monitor_loop import crash_recovery_loop, orphan_recovery_loop
from app.core.scheduler_loop import promote_scheduled_loop
from app.redis_client import connect, disconnect

shutdown = False


def handle_sigterm(*args):
    global shutdown
    shutdown = True


signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)


class _JSONFormatter(logging.Formatter):
    _SKIP = frozenset({
        "name", "msg", "args", "created", "filename", "funcName",
        "levelname", "levelno", "lineno", "module", "msecs", "pathname",
        "process", "processName", "relativeCreated", "thread", "threadName",
        "exc_info", "exc_text", "stack_info", "taskName",
    })

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._SKIP and not key.startswith("_"):
                data[key] = value
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data)


def _setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JSONFormatter())
    logging.basicConfig(level=settings.LOG_LEVEL, handlers=[handler], force=True)


async def main() -> None:
    _setup_logging()
    logging.getLogger(__name__).info("Scheduler process starting")
    await connect()
    try:
        await asyncio.gather(
            promote_scheduled_loop(lambda: shutdown),
            crash_recovery_loop(lambda: shutdown),
            orphan_recovery_loop(lambda: shutdown),
        )
    finally:
        await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
