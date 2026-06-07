### `cost-audit-runner` (Sonnet) — AWS waste hunt
| "find AWS waste", "idle/orphaned resources", "cost cleanup sweep", multi-service describe sweeps | `cost-audit-runner` |
| Spend totals / trends / forecast / cost-by-tag | `cost-explorer` |
⛔ Chaining multiple `Bash(aws ... describe/list ...)` calls to hunt waste inline
Note: strictly read-only; never executes the `fix_commands` it returns.
