# AI Tool Usage

## Tools I Used

Claude (claude.ai) was used throughout the development process for architecture design, code generation, and iterative refinement.

## What Helped Most

**Boilerplate speed** — docker-compose, Dockerfile, SQLAlchemy async engine setup, and FastAPI lifespan wiring were generated significantly faster than writing from scratch. These are largely deterministic once the stack is decided, so AI was a good fit. This allowed me to spend more time on concurrency, recovery, retry behaviour, and failure-mode analysis.

**Partial indexes** — Claude suggested PostgreSQL partial indexes filtered by job status (`WHERE status = 'processing'`, `WHERE status = 'pending'`). I kept them after understanding the reasoning: completed and failed rows will eventually dominate the table, and a standard index would scan all of them. The partial indexes keep the crash recovery and orphan recovery queries fast regardless of historical data volume.

## What I Had to Fix

**State ownership** — An early iteration suggested storing job state (attempts, progress, results) in Redis alongside queue metadata. I rejected this after thinking through the failure modes — Redis is volatile, and a restart or memory eviction would lose everything. The final architecture keeps PostgreSQL as the sole source of truth and uses Redis only as a signalling layer. This is also what makes orphan recovery possible: if Redis loses its queue entries, the scheduler can re-signal any pending jobs from Postgres within minutes.

**Transaction result handling** — Claude initially placed `fetchone()` after `commit()` in the atomic claim pattern. I changed the ordering so the ownership decision is made before the transaction is finalized. The row is fetched first, then the transaction is either committed (ownership acquired) or rolled back (no row returned). This pattern is now consistent across every `UPDATE ... RETURNING` claim in the codebase.

## What Required Extra Validation

**JSONB serialization** — The interaction between SQLAlchemy, asyncpg, and PostgreSQL JSONB columns needed extra attention. Claude suggested `json.dumps()` and explicit `::jsonb` casts in raw SQL — both unnecessary. asyncpg serializes Python dictionaries natively, so the final implementation passes dicts directly and lets the driver handle encoding.

**Concurrency edge cases** — I spent extra time validating ownership races, retry scheduling, and scheduler promotion logic to make sure duplicate Redis signals could never cause duplicate job execution. The single ownership gate is PostgreSQL's atomic `UPDATE ... WHERE status='pending' RETURNING *` — even if the same job ID appears in Redis twice, only one worker gets the row back.