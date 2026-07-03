## Alembic migrations — `alembic-migration` skill
Key rules: new `NOT NULL` column needs `server_default` (drop in follow-up); no million-row `UPDATE` in `upgrade()` — backfill in background job; `ALTER TYPE … ADD VALUE` is non-transactional → own migration in `autocommit_block()`. Preview with `alembic upgrade head --sql`; round-trip the downgrade.
