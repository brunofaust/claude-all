### `secrets-fetcher` (Haiku) — Secrets Manager reads
| `aws secretsmanager get-secret-value/list-secrets/describe-secret` | `secrets-fetcher` |
⛔ `Bash(aws secretsmanager get-secret-value ...)` inline — **secret value lands in transcript verbatim**
⛔ `Bash(TOKEN=$(aws secretsmanager get-secret-value ...))` — same leak; delegate the lookup
Note: returns ARN + top-level JSON keys only; NEVER echoes secret values.
