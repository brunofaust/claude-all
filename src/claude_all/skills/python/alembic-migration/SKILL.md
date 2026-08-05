---
name: alembic-migration
description: >-
  Generate Alembic migrations following myapp patterns — naming, backfill safety, merge resolution, ENUM handling, asyncpg query syntax. Use when: creating a new alembic revision, adding/dropping/renaming columns, adding/altering ENUM types, backfilling data, merging divergent branches, resolving migration drift, running `alembic upgrade/downgrade`, debugging failed migrations, reviewing migration PRs.
disable-model-invocation: false
user-invocable: true
---

# Alembic Migration Skill (myapp)

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

For ENUM changes that rename/remove values or need a same-change backfill:
create new type, migrate data, drop old type in a SEPARATE migration. For pure
value ADDITIONS, the in-place `ALTER TYPE ... ADD VALUE` inside an autocommit
block is fine — see "ENUM ALTER inside autocommit block" below.

### Adding + dropping columns

NEVER add and drop columns on the same table in the same migration. Two
separate migrations. Acquires fewer + shorter locks, easier rollback.

### Renames

Use op functions, not raw SQL:

```python
op.alter_column("orders", "old_name", new_column_name="new_name")
op.rename_table("old_table", "new_table")
```

Skip `op.batch_alter_table()` — that's a SQLite-compat shim. myapp is
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

### Gate it: `checkers/alembic_heads.py`

`uv run alembic heads` catches a fork only when someone remembers to run it.
This skill ships a runnable AST checker at `checkers/alembic_heads.py` that
turns the pre-flight check into a gate: wire it into prek/pre-commit as a
`language = "system"` hook on `alembic/versions/*.py`, and it fails the commit
the moment two migrations independently branch off the same parent — before
the fork ever reaches `main` — plus it catches a revision id too long for
`alembic_version.version_num VARCHAR(32)` on a fresh database. Pure AST parse,
no alembic import, no DB connection, fast enough for every commit.

```bash
uv run python checkers/alembic_heads.py alembic/versions
```

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
1. Deploy
1. Run a separate background job (script, dbt model, lambda) to compute
    the real values
1. In a follow-up migration, drop the `server_default`

Don't do million-row UPDATEEs inside `upgrade()` — they hold transaction-level
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

## ENUM ALTER inside autocommit block

**Common foot-gun.** On PostgreSQL < 12, `ALTER TYPE ... ADD VALUE` cannot run
inside the implicit transaction Alembic wraps each migration in — it fails with:

```
ERROR: ALTER TYPE ... ADD cannot run inside a transaction block
```

Since PG 12 it CAN run in a transaction, but the new value is unusable until the
transaction commits — so a same-migration backfill that writes the new value
still breaks. Either way, use `op.get_context().autocommit_block()` to escape
the outer transaction. (This in-place `ADD VALUE` route is for *adding* values
only; for renames/removals — or when you must backfill in the same change — use
the new-type → migrate → drop-old recipe from "ENUM value additions" above.)

```python
from alembic import op


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE order_status ADD VALUE IF NOT EXISTS 'refunded'")
        op.execute("ALTER TYPE order_status ADD VALUE IF NOT EXISTS 'disputed'")
```

Notes:

- `IF NOT EXISTS` makes the statement re-runnable (safe on partially-applied
    migrations).
- Works with asyncpg-driven Alembic (myapp setup) — the autocommit block
    uses a separate connection state, no special async handling needed.
- Don't mix DDL + data migration in the same autocommit block — if the data
    step fails, the ENUM value is already committed and can't be rolled back.
    Split into two migrations: one for the ENUM additions (autocommit), one for
    data using the new value (normal transaction).

## Zero-downtime column rename (expand-contract)

`op.alter_column(... new_column_name=...)` takes an `ACCESS EXCLUSIVE` lock and
rewrites the column metadata — on a hot table it blocks every reader and
writer until done. **Never do it directly in production.**

Use the 5-step expand-contract pattern, split across at least two migrations
and one app deploy:

1. **Add new column** (nullable, or with `server_default`) — fast metadata-only
    op.
1. **Dual-write** — application writes BOTH old + new columns. Deploy.
1. **Backfill** old → new in batches via a background job (NOT inline in the
    migration — see "Backfill of existing data" above).
1. **Switch reads** to the new column. Deploy.
1. **Drop old column** in a separate migration once you're confident nothing
    reads it.

Concrete example — renaming `orders.user_id` → `orders.customer_id`:

```python
# 140_add_customer_id_to_orders.py
def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("customer_id", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_orders_customer_id", table_name="orders")
    op.drop_column("orders", "customer_id")
```

```python
# 145_drop_orders_user_id.py — runs AFTER app fully migrated to customer_id
def upgrade() -> None:
    op.drop_column("orders", "user_id")


def downgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("user_id", sa.BigInteger(), nullable=True),
    )
    # NOTE: backfill from customer_id is the app's responsibility on rollback.
```

Between migrations 140 and 145: deploy app version that dual-writes, run
backfill, deploy app version that reads `customer_id`, verify, THEN apply 145.

## `alembic stamp` — recovery only

When prod history diverges from migration files (manual hotfix applied
directly to DB, restored from a snapshot, etc.), `alembic stamp` marks the
database at a specific revision **without running any migration code**:

```bash
uv run alembic stamp <revision_hash>      # mark DB at this revision
uv run alembic stamp head                 # mark DB as up-to-date
```

**Recovery-only.** Stamping skips the actual schema change — the DB and the
migration history are now claimed to match, whether they do or not. Verify
schema manually before stamping:

```bash
uv run alembic upgrade head --sql > /tmp/expected.sql
# compare against current DB structure
```

NEVER use `stamp` to "fix" a failed migration on a normal flow — debug the
migration, downgrade properly, retry. Stamp is for genuine drift recovery
(post-restore, post-manual-hotfix) only.

## Anti-patterns

| Anti-pattern                                                  | Why                             | Use instead                                       |
| ------------------------------------------------------------- | ------------------------------- | ------------------------------------------------- |
| `op.add_column(..., nullable=False)` without `server_default` | Fails on existing data          | Add `server_default`, drop in follow-up           |
| `IN :param` with asyncpg                                      | Doesn't work                    | `= ANY(:param)` with list                         |
| Add + drop column in one migration                            | Lock contention                 | Two migrations                                    |
| `ALTER TYPE ... ADD VALUE` inline with data migration         | Non-transactional, can deadlock | New type → migrate → drop old                     |
| `op.batch_alter_table()`                                      | SQLite compat — irrelevant      | Plain op functions                                |
| Inline million-row UPDATE                                     | Holds locks, blocks writes      | Background job + follow-up migration              |
| Empty `downgrade()` left as autogen `pass`                    | Silently irreversible           | Explicit reverse, or `raise NotImplementedError`  |
| Rewriting alembic history (squash old migrations)             | Breaks staging/prod alignment   | Leave history alone; refactor models, not history |
| Raw `op.execute("ALTER TABLE …")` for ops `op.*` supports     | Not dialect-checked, typo-prone, autogen can't reverse it | `op.add_column` / `op.alter_column` / `op.create_index`; reserve `op.execute` for what op funcs can't do (`ALTER TYPE … ADD VALUE`, `CREATE INDEX CONCURRENTLY`) |

## Reference migrations

- `133_*.py` — backfill pattern with documented row defaults
- (add others as the project grows)
