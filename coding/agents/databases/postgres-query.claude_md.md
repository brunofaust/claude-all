### Command dispatch — Postgres queries → `postgres-query` (Haiku, read-only)

| Command | Agent |
|---|---|
| `psql ...`, run a SELECT / EXPLAIN / SHOW, inspect a table, check a query plan (non-AWS Postgres) | `postgres-query` |

Anti-patterns:

- `Bash(psql ... -c "SELECT ...")` inline — result sets and table metadata are verbose and wrap badly. Delegate to `postgres-query` and act on the summarized rows.
- For AWS RDS Postgres specifically, use `rds-postgres-query` (handles IAM auth / RDS Proxy), not this one.

Note: `postgres-query` is READ-ONLY — SELECT / EXPLAIN / SHOW / pg_* / information_schema only; never INSERT/UPDATE/DELETE/DDL. A trivial `psql -c "SELECT 1"` connectivity check can stay inline.
