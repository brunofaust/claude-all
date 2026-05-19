---
name: alembic-migration
description: >
  Generate Alembic migrations following busydone patterns — naming, backfill
  safety, merge resolution, ENUM handling, asyncpg query syntax.
  Use when: creating a new alembic revision, adding/dropping/renaming columns,
  adding/altering ENUM types, backfilling data, merging divergent branches,
  resolving migration drift, running `alembic upgrade/downgrade`, debugging
  failed migrations, reviewing migration PRs.
disable-model-invocation: false
user-invocable: true
---

# Alembic Migration Skill (busydone)

PostgreSQL + asyncpg + Alembic. Production datalake — migrations run against
live data with hundreds of millions of rows. Safety + reviewability matter
more than cleverness.

## Pre-flight (always)

Before writing a migration:

```bash
uv run alembic heads                  # one head = clean; two+ = need merge
uv run alembic current                # what's deployed
uv run alembic history --indicate-current
uv run alembic check                  # any pending autogen drift?
```

If `heads` shows multiple, resolve with a merge migration FIRST (see "Merge"
below). Never stack a new revision on top of an unmerged branch.

## Naming

Format: `{number}_{snake_case_description}.py` where:

- `{number}` = next int after current max (e.g. `134_add_status_column.py`)
- `{snake_case_description}` is short, verb-first, no article
- The `revision = "..."` identifier inside the file is alembic's auto-generated
  hash — do NOT change it. The filename number is for humans only.

```python
"""Add status column to orders.

Revision ID: a3f8b2c1d4e5
Revises: 9c2d1e0f8a7b
Create Date: 2026-05-19 10:00:00
"""
```

## Schema rules

### New NOT NULL columns

NEVER add a NOT NULL column without `server_default` — existing rows have
nothing to put there and the migration fails on tables with data.

Pattern: two-migration backfill.

```python
# 134_add_status_to_orders.py — has server_default
def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="pending",
        ),
    )

# 135_drop_status_default.py — runs AFTER deploy + backfill verification
def upgrade() -> None:
    op.alter_column("orders", "status", server_default=None)
```

Document in the migration comment what existing rows get:

```python
"""Add status column to orders.

Backfill: existing rows get 'pending' via server_default.
Follow-up migration 135 drops the default once new writes always populate it.
"""
```

### ENUM types

Always idempotent — `CREATE TYPE ... IF NOT EXISTS` via raw SQL, never `sa.Enum(create_type=True)` on a re-runnable migration.

```python
def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'order_status') THEN
                CREATE TYPE order_status AS ENUM ('pending', 'shipped', 'cancelled');
            END IF;
        END$$;
    """)
    op.add_column(
        "orders",
        sa.Column(
            "status",
            postgresql.ENUM(name="order_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
    )
```

For ENUM value additions: create new type, migrate data, drop old type in a
SEPARATE migration. Don't combine — postgres `ALTER TYPE ... ADD VALUE` is not
transactional in some setups and can deadlock.

### Adding + dropping columns

NEVER add and drop columns on the same table in the same migration. Two
separate migrations. Acquires fewer + shorter locks, easier rollback.

### Renames

Use op functions, not raw SQL:

```python
op.alter_column("orders", "old_name", new_column_name="new_name")
op.rename_table("old_table", "new_table")
```

Skip `op.batch_alter_table()` — that's a SQLite-compat shim. busydone is
postgres only. Adding it is noise and obscures the actual ALTER TABLE.

## Query syntax (asyncpg)

`= ANY(:param)` with a list, NEVER `IN :param`:

```python
# YES
result = await session.execute(
    sa.text("SELECT * FROM orders WHERE id = ANY(:ids)"),
    {"ids": [1, 2, 3]},
)

# NO — fails with asyncpg
result = await session.execute(
    sa.text("SELECT * FROM orders WHERE id IN :ids"),
    {"ids": [1, 2, 3]},
)
```

Quote PostgreSQL reserved keywords:

```python
op.execute('ALTER TABLE accounts ADD COLUMN "type" VARCHAR(20)')
op.execute('SELECT * FROM links WHERE "references" IS NOT NULL')
```

## Multi-branch merges

Two heads = two devs created revisions off the same parent. Resolve with a
NO-OP merge migration:

```bash
uv run alembic merge -m "merge feature-x and feature-y" <head1> <head2>
```

The generated file should have empty `upgrade()` and `downgrade()`. If alembic
suggested actual changes, something is wrong — investigate before applying.

## Downgrade

Always implement `downgrade()` — even if it's logically a no-op (e.g.
backfilled data can't be cleanly reversed):

```python
def downgrade() -> None:
    op.drop_column("orders", "status")
    op.execute("DROP TYPE IF EXISTS order_status")
```

For data-only migrations where reversal isn't meaningful, raise:

```python
def downgrade() -> None:
    raise NotImplementedError("data backfill cannot be reversed")
```

## Backfill of existing data

Inline backfill is OK for small tables (< 1M rows, < 30s). For anything
larger:

1. Add the column with `server_default` (sets all existing rows fast)
2. Deploy
3. Run a separate background job (script, dbt model, lambda) to compute
   the real values
4. In a follow-up migration, drop the `server_default`

Don't do million-row UPDATEs inside `upgrade()` — they hold transaction-level
locks and block writes.

## Preview before applying

```bash
uv run alembic upgrade head --sql > /tmp/migration.sql
```

Read it. Confirm:
- No surprise `DROP` statements
- Index creation uses `CONCURRENTLY` for big tables (raw SQL — alembic can't
  do this via op functions)
- No `ALTER TABLE ... USING` casts on huge tables (full rewrite)

## Validation

```bash
uv run alembic upgrade head           # apply
uv run alembic check                  # any drift between models and DB?
uv run alembic downgrade -1           # round-trip test
uv run alembic upgrade head           # back to head
```

If `alembic check` reports drift after applying, your migration didn't match
the SQLAlchemy model — either the model is wrong or the migration is.

## Commits

One migration per commit. Message format:

```
feat(migration 134): add status column to orders

Backfill: existing rows get 'pending'. Follow-up 135 drops default.
```

Reference the migration number in the subject. Body explains backfill +
follow-up plan if applicable.

## Anti-patterns

| Anti-pattern | Why | Use instead |
|---|---|---|
| `op.add_column(..., nullable=False)` without `server_default` | Fails on existing data | Add `server_default`, drop in follow-up |
| `IN :param` with asyncpg | Doesn't work | `= ANY(:param)` with list |
| Add + drop column in one migration | Lock contention | Two migrations |
| `ALTER TYPE ... ADD VALUE` inline with data migration | Non-transactional, can deadlock | New type → migrate → drop old |
| `op.batch_alter_table()` | SQLite compat — irrelevant | Plain op functions |
| Inline million-row UPDATE | Holds locks, blocks writes | Background job + follow-up migration |
| Empty `downgrade()` left as autogen `pass` | Silently irreversible | Explicit reverse, or `raise NotImplementedError` |
| Rewriting alembic history (squash old migrations) | Breaks staging/prod alignment | Leave history alone; refactor models, not history |

## Reference migrations

- `133_*.py` — backfill pattern with documented row defaults
- (add others as the project grows)
