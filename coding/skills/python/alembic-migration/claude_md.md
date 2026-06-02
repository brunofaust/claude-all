## Alembic migrations — alembic-migration skill

When creating or altering an Alembic migration (add/drop/rename columns, ENUM changes, backfills, merging divergent heads, resolving drift), apply the `alembic-migration` skill.

- New `NOT NULL` column needs a `server_default` (drop it in a follow-up). No million-row `UPDATE` inside `upgrade()` — backfill in a background job.
- `ALTER TYPE … ADD VALUE` is non-transactional → its own migration in an `autocommit_block()`, separate from any data migration.
- asyncpg: `= ANY(:param)` not `IN`; prefer `op.add_column`/`op.alter_column` over raw `op.execute`.
- Preview with `alembic upgrade head --sql`; round-trip the downgrade; `alembic check` for model/DB drift.

Review a significant migration with the `migration-reviewer` agent before applying.
