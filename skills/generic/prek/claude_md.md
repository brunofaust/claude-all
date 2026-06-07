## prek / pre-commit — `prek` skill
Apply when setting up git hooks, debugging hook failures, or resolving findings.

Rules: `prek run --all-files` is the single gate — never substitute individual `ruff`/`mypy` runs. Delegate to `code-quality` agent. Fix order: fix → narrow allowlist → scope-exclude (never `--no-verify`). Max 2 consecutive prek failures, then surface verbatim to user.
