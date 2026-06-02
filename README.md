# Job Queue System

Distributed background job processing system built with FastAPI, PostgreSQL, and Redis.

## Stack

- **FastAPI** — async HTTP API
- **PostgreSQL** — single source of truth for all job state
- **Redis** — signal/delivery layer only (sorted sets, no job state)
- **SQLAlchemy 2.0 async** + asyncpg
- **Pydantic v2**
- **Docker + docker-compose**

## How to Run

```bash
docker-compose up --build
```

Starts 5 services: `api`, `worker`, `scheduler`, `postgres`, `redis`.

## How to Run Tests

```bash
# Fast tests — no worker or scheduler needed
# Covers: submission, cancellation, idempotency, priority ordering,
#         health endpoint, and scheduled job placement (6 modules, ~20 tests)
docker-compose run --rm api pytest tests/ -v -m "not integration"

# All tests including integration (worker + scheduler must be running)
docker-compose up --build -d
docker-compose run --rm api pytest tests/ -v

# Retry integration tests require FORCE_WEBHOOK_FAIL on both the worker and test runner
FORCE_WEBHOOK_FAIL=true docker-compose up --build -d
docker-compose run --rm -e FORCE_WEBHOOK_FAIL=true api pytest tests/test_retry.py -v
```

> **Note:** Retry integration tests take ~5 minutes — webhook jobs exhaust 5 attempts
> with backoff delays of 0 s → 30 s → 120 s → 120 s before reaching `failed`.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/jobs` | Submit a job |
| `GET` | `/jobs` | List jobs (filter by `status`, `type`, `priority`) |
| `GET` | `/jobs/{id}` | Get job status / result |
| `POST` | `/jobs/{id}/cancel` | Cancel a pending or scheduled job |
| `POST` | `/jobs/{id}/retry` | Re-enqueue a failed job |
| `GET` | `/health` | Queue sizes and job counts |

## Job Types

| Type | Simulated work | Max attempts | Result |
|------|---------------|--------------|--------|
| `email` | 1–3 s sleep | 3 | `{ "message_id": "mock-…" }` |
| `webhook` | 1–2 s, 20% random failure | 5 | `{ "webhook_id": "mock-…", "status": "delivered" }` |
| `report` | 3–5 s sleep | 1 | `{ "file_url": "mock://reports/….pdf", "generated_at": "…" }` |
| `batch` | 0.5 s per item, progress tracked | 3 | `{ "processed": n, "summary": "…" }` |

All handlers are mocks. Batch jobs update `progress` in the DB every 10 percentage points.

## Configuration

All values are read from environment variables. Defaults are suitable for local development.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://jobqueue:jobqueue@localhost:5432/jobqueue` | asyncpg connection string |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection string |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `WORKER_CONCURRENCY` | `1` | Number of jobs processed concurrently per worker |
| `CRASH_RECOVERY_TIMEOUT_MINUTES` | `10` | How long before a stuck `processing` job is recovered |
| `ORPHAN_RECOVERY_MINUTES` | `2` | How long before a stuck `pending` job is re-signalled to Redis |
| `BACKOFF_DELAYS` | `[0, 30, 120]` | Retry delay in seconds per attempt |
| `FORCE_WEBHOOK_FAIL` | `false` | Force webhook handler to always fail (for deterministic retry tests) |

## How to Submit Test Jobs

```bash
# Email job
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"type": "email", "payload": {"to": "test@test.com"}, "priority": 5}'

# Webhook job
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"type": "webhook", "payload": {"url": "https://example.com"}}'

# Batch job
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"type": "batch", "payload": {"items": [1,2,3,4,5,6,7,8,9,10]}}'

# Scheduled job (30 seconds from now)
FUTURE=$(python3 -c "
from datetime import datetime, timezone, timedelta
print((datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat())
")
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d "{\"type\": \"email\", \"payload\": {}, \"run_at\": \"$FUTURE\"}"

# Idempotent submission (run twice — returns same job id)
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"type": "email", "payload": {}, "idempotency_key": "my-unique-key"}'
```

## Architecture

```
  ┌──────────────────────────────────────────────────────────┐
  │                      PostgreSQL                           │
  │             (source of truth for all job state)           │
  └───────────────┬─────────────────┬────────────────────────┘
    INSERT/SELECT │          UPDATE  │ claim/complete/recover
                  │                  │
          ┌───────┴──┐         ┌─────┴──────┐       ┌────────────┐
          │   API    │         │   Worker   │        │  Scheduler │
          └───────┬──┘         └──────┬─────┘        └──────┬─────┘
       ZADD       │       ZPOPMAX     │  ZADD (retry)        │ ZADD/ZRANGEBYSCORE/ZREM
                  │                   │                       │
                  └───────────────────┴───────────────────────┘
                                      │
                              ┌───────┴───────┐
                              │     Redis      │
                              │  jobs:queue    │  ← sorted by priority score
                              │  jobs:scheduled│  ← sorted by run_at timestamp
                              └───────────────┘
```

Redis holds **job IDs only** — scores encode priority and submission order.
All status, result, and attempt data lives exclusively in PostgreSQL.

See [DECISIONS.md](DECISIONS.md) for design rationale and trade-offs.
