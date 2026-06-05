### Command dispatch — AWS RDS/Aurora Postgres queries → `rds-postgres-query` (Haiku, read-only)

| Command | Agent |
|---|---|
| `psql` against RDS/Aurora, any SELECT / EXPLAIN / SHOW / pg_* on AWS Postgres | `rds-postgres-query` |

Anti-patterns:

- `Bash(PGPASSWORD=... psql -h ...rds... )` inline — this **leaks credentials** into the transcript AND skips Secrets Manager / IAM auth. Always delegate to `rds-postgres-query`, which resolves auth and returns summarized rows.
- For non-AWS Postgres (local / Docker / Supabase / Neon), use `postgres-query` instead.

Note: `rds-postgres-query` is READ-ONLY (SELECT / EXPLAIN / SHOW / pg_*); it resolves credentials via Secrets Manager / IAM, never inline. Never INSERT/UPDATE/DELETE/DDL.
