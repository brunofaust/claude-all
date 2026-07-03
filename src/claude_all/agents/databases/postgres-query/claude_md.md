### `postgres-query` (Haiku) — local/non-AWS Postgres (read-only)
| `psql`, SELECT/EXPLAIN/SHOW, non-AWS Postgres (local, Docker, Supabase, Neon) | `postgres-query` |
⛔ `Bash(psql ... -c "SELECT ...")` inline for anything beyond a `SELECT 1` connectivity check
Note: for AWS RDS/Aurora use `rds-postgres-query` (handles IAM auth).
