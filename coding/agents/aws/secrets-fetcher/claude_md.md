### Command dispatch — Secrets Manager reads → `secrets-fetcher` (Haiku, read-only)

| Command | Agent |
|---|---|
| `aws secretsmanager get-secret-value/list-secrets/describe-secret` | `secrets-fetcher` |

Anti-patterns:

- `Bash(aws secretsmanager get-secret-value ...)` inline — the secret **value lands in the transcript verbatim** (and in any session-memory / indexing). ALWAYS delegate to `secrets-fetcher`, which returns the structure (ARN, top-level keys, rotation, KMS) WITHOUT echoing values.
- `Bash(TOKEN=$(aws secretsmanager get-secret-value ...))` to unwrap a secret into an env var — same leak risk; delegate the lookup.

Note: `secrets-fetcher` NEVER echoes secret values — only the ARN, last-rotated date, top-level JSON keys, version stage, and KMS key. Read-only.
