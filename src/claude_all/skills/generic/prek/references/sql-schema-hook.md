# If your repo has embedded SQL: an SQL-against-schema gate

For a Python+SQL codebase, a very high-value `local` hook validates **embedded SQL strings against the
schema folded from your migrations — with no database**. It catches "column/table doesn't exist" and
typo'd identifiers at commit time, the class of bug a fully-mocked DB test can't see. Suggest creating
it when you see raw SQL strings (`cur.execute("SELECT …")`, query builders with literal column lists)
in a repo that owns its migrations. Sketch:

1. Fold the migration files into a virtual `{table: [columns]}` schema (static parse — don't import
   and don't hit a DB).
2. Extract embedded SQL via a cheap regex prefilter, then confirm with an `ast` walk over string
   literals passed to `execute`/`executemany`.
3. Validate each statement with [`sqlglot`](https://github.com/tobymao/sqlglot) against that schema.

Hooks that make or break it (a naive build misses these):

- `sqlglot.optimizer.qualify(..., validate_qualify_columns=True)` validates **SELECT** columns but
  **not** DML — write a light resolver for `INSERT`/`UPDATE`/`DELETE` (including `INSERT` column lists).
- `qualify` **stops at the first** unresolved column, so one query can hide several bugs — surface
  findings iteratively (re-run after each fix) or document the limitation.
- sqlglot **parses a trailing comma before a clause keyword leniently** (`SELECT a, FROM t`) — add a
  dedicated regex for that class; the optimizer won't flag it.
- `ON CONFLICT (<expression>)` targets may not parse — retry with the conflict target stripped before
  declaring a parse error.
- Handle system columns, `unnest(...)` / table-function aliases, subquery sources, and `:name` bind
  params (these parse natively in the **postgres** dialect — no substitution needed).
- **Gate version-specific syntax against your PRODUCTION engine version** (e.g. a clause valid only on
  a newer major than prod runs) — validating against a newer sqlglot dialect than prod will pass SQL
  that fails in production.

`sqlglot` is the only extra dependency; add it to the hook's `additional_dependencies`. Pair it with
the `regression-gates` baseline harness: on first run it WILL find real bugs — baseline them and burn
down. (This gate is stack-specific and not shipped in claude-all; it lives here as a recipe to
instantiate per project.)
