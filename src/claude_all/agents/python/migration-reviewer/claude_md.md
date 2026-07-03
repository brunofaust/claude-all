### `migration-reviewer` (Sonnet) — Alembic migration review
| "review this migration", "is this migration safe", "alembic duplicate revision / divergent heads", "check migration before deploy" | `migration-reviewer` |
⛔ Reviewing a migration inline in main session
Note: read-only — runs only read-only alembic introspection (heads / current / history); never applies migrations. Returns a risk-scored report (BLOCK / WARN / INFO).
