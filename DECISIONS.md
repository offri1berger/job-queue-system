# Design Decisions

## 1. Job Pickup Strategy — Atomic DB Claim

**Approach:** `UPDATE jobs SET status='processing' ... WHERE id=:id AND status='pending' RETURNING *`

Redis `ZPOPMAX` delivers a job ID as a **signal only**. The real ownership gate is the DB `UPDATE` — only the worker that receives a row back from `RETURNING *` owns the job. If two workers race on the same job ID, the second gets zero rows and skips.

`fetchone()` is called **before** `commit()`. In asyncpg, cursor results are tied to the open transaction; committing first can flush the result set before it is read. The safe ordering is: fetch the row, check if it exists, then either commit (row present — we own the job) or rollback (no row — skip).

**Trade-offs:** One extra DB round-trip per job vs. a pure Redis lock. The benefit is that job state survives Redis restarts with no data loss, and the claim logic is a single atomic SQL statement rather than a Redis Lua script.

---

## 2. Worker Crash Recovery — Visibility Timeout

**Approach:** Scheduler loop 2 scans for `status='processing' AND locked_at < NOW() - INTERVAL '10 minutes'` every 60 seconds. Matching jobs are reset to `pending` and re-enqueued.

The 10-minute window is chosen to comfortably cover the longest expected job (report jobs sleep 3–5 s in this mock, but in production could be much longer). The `locked_at` column records when the worker claimed the job.

**What happens on crash:** The job stays `processing` until the monitor loop detects it. After 10 minutes it is recovered and re-processed from scratch. For batch jobs, this means progress is reset to 0 — partial work is discarded.

**Trade-offs:** Simple and requires no worker cooperation — workers do not need to update any heartbeat column during execution. The downside is the coarse 10-minute window. See section 9 for the heartbeat improvement.

---

## 3. Priority Queue — Composite Redis Score

**Approach:** `score = priority × 1_000_000_000_000 − created_at_ms`

`ZPOPMAX` pops the highest-scoring job. Higher priority multiplied by 1 trillion dominates the score, ensuring correct ordering across any realistic priority values. Within the same priority, the lower `created_at_ms` subtracts less, giving older jobs a higher score (FIFO).

All `ZADD jobs:queue` calls go through the single function in `app/core/queue_score.py`. No inline score calculation anywhere else.

**Trade-offs:** The composite score is non-obvious. Centralising it in `queue_score.py` makes inconsistencies impossible — there is only one place to change if the formula ever needs updating.

---

## 4. Retry Backoff — Reuses Scheduled Mechanism

**Approach:** `BACKOFF_DELAYS = [0, 30, 120]` seconds. Attempt 1 → immediate re-queue; attempts 2+ → `status='scheduled', run_at=NOW()+delay`, pushed to `jobs:scheduled`. Scheduler loop 1 promotes it back to pending when `run_at` arrives.

There is no separate retry queue. The scheduled job path is reused unchanged, which means the retry logic is a single step: compute `run_at`, write to DB, push to Redis.

**Trade-offs:** The delay for attempt 4 and beyond is capped at 120 s (last element in the list). A production system would extend the list or use exponential backoff. Both `BACKOFF_DELAYS` and `MAX_ATTEMPTS_BY_TYPE` live in config so they can be tuned per environment without a code change.

---

## 5. Scheduler Race Condition — Single Instance

**Approach:** Single scheduler instance. No distributed locking.

Loop 1's inner `UPDATE WHERE status='scheduled' RETURNING *` is idempotent: if two schedulers raced (hypothetically), only one would get a row back and only one would push to Redis. The DB claim in the worker prevents double-processing regardless.

**Trade-offs:** Safe with one instance; unsafe with two without additional coordination. See section 9 for scale-out options.

---

## 6. Redis as Signal Layer Only

**Approach:** Redis sorted sets hold job IDs and scores only. No job state (attempts, payload, result, status) ever lives in Redis.

**Why it matters concretely:** Suppose the Redis pod is OOM-killed at 2 am. Every entry in `jobs:queue` and `jobs:scheduled` is gone. Because Postgres is the sole source of truth, no data is lost — every job's status, payload, and attempt count is still in the `jobs` table. Orphan recovery (scheduler loop 3) scans for `status='pending' AND updated_at < NOW() - 2 minutes` and re-signals every affected job to Redis within one loop cycle. Workers resume processing within minutes of Redis coming back up, with no manual intervention.

**Trade-offs:** Requires the orphan recovery loop to run reliably. If the scheduler also goes down during the same outage, pending jobs are stuck until the scheduler restarts — but they are never lost or double-processed.

---

## 7. Session Per Operation

**Approach:** Every DB step opens and closes its own `async with AsyncSessionLocal() as db:` block. The worker uses separate sessions for the claim, the success update, and each failure/retry update. The batch handler uses completely isolated sessions for progress writes.

**Why:** Sharing a single session across the full job lifecycle would tie a DB connection to the job's entire execution time (up to several minutes for report or batch jobs). With a session per operation, connections are held only for the duration of each SQL statement and returned to the pool immediately.

**Trade-offs:** More connection pool churn. The batch handler's progress writes (one session per 10% increment) are the most frequent case — a 100-item batch opens and closes ~10 sessions during execution.

---

## 8. Idempotency via PostgreSQL Unique Constraint

**Approach:** `idempotency_key` has a `UNIQUE` constraint in Postgres. The API checks for an existing row with `SELECT WHERE idempotency_key = :key` before inserting. If found, the existing job is returned with HTTP 200.

The check happens at the application layer rather than relying on a constraint violation + catch, which keeps the error path clean. The `UNIQUE` constraint is the ultimate safety net if two requests race past the SELECT simultaneously.

**Why not Redis `SETNX`:** Redis is volatile. A key written to Redis for idempotency would be lost on restart, allowing a duplicate job to be created after recovery. Storing the constraint in Postgres means it survives any Redis failure.

---

## 9. What I Would Do With More Time

1. **Worker heartbeats** — `UPDATE locked_at=NOW()` every 30 s during execution, allowing a 2-minute recovery timeout instead of 10 minutes without risk of falsely reclaiming an active job.
2. **Dead-letter queue** — After `max_attempts`, move permanently-failed jobs to a separate table for manual inspection and replay rather than leaving them in the main `jobs` table with `status='failed'`.
3. **Redis Lua atomicity for scheduler scale-out** — Wrap `ZRANGEBYSCORE + ZREM + ZADD jobs:queue` in a Lua script, or use `pg_try_advisory_lock`, to allow multiple scheduler instances to run safely.
4. **Distributed tracing** — Propagate a trace ID through job submission, worker execution, and all log lines to correlate a job's full lifecycle in one trace.
5. **Batch job cancellation** — A cooperative cancellation token checked between items would allow a processing batch job to be cancelled mid-flight rather than waiting for the crash recovery window.
