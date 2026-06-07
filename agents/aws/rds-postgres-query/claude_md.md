### `rds-postgres-query` (Haiku) — AWS RDS/Aurora Postgres (read-only)
| `psql` against RDS/Aurora, SELECT/EXPLAIN/SHOW/pg_* on AWS Postgres | `rds-postgres-query` |
⛔ `Bash(PGPASSWORD=... psql -h ...rds... )` — **credential leak** + skips IAM auth
Note: for non-AWS Postgres (local/Docker/Supabase/Neon) use `postgres-query` instead.
