### Command dispatch — fixing lint / type / quality findings → `lint-fixer` (Sonnet)

| Goal | Agent |
|---|---|
| "fix the lint/ruff/mypy/eslint/tsc errors", "resolve codecongruence", "make prek pass" | `lint-fixer` |
| REPORT findings without fixing (read-only) | `code-quality` (haiku) |
| Proactive style modernization (PEP 695, async, etc.) | `python-refactorer` (sonnet) |

Anti-patterns:
- Fixing ruff/mypy/codecongruence findings in the main (Opus) session — these are Sonnet-class fixes.
  Delegate to `lint-fixer`; don't burn Opus on them.
- "Fixing" a finding by adding `# type: ignore` / `# noqa` / loosening config / `--no-verify` — that's
  silencing, not fixing. `lint-fixer` is built to refuse this and fix the root cause.
- Asking `code-quality` to fix — it's read-only (finds only). Find with `code-quality` → fix with
  `lint-fixer` → confirm no regression with `test-runner`.

`lint-fixer` clears the mechanical tier with `ruff --fix`/`ruff format` first, then fixes judgment
findings (mypy types, PLR complexity, codecongruence dedup) one category at a time, root-cause only,
and re-runs the gate + tests after each. Max 2 attempts per category, then surfaces verbatim. Never
weakens thresholds or silences findings.
