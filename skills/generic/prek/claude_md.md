## prek / pre-commit — prek skill

When setting up or configuring git hooks, debugging a hook failure, or resolving a finding, apply the `prek` skill. It covers **both** prek (fast Rust runner, `prek.toml`) and pre-commit (`.pre-commit-config.yaml`) — same hooks, IDs, stages, and `SKIP=`.

- `prek run --all-files` is the single gate — never run `ruff`/`mypy`/`eslint` individually and call it "passed". Delegate to the `code-quality` agent.
- Resolve a finding by **fix → narrow allowlist (word/rule/line) → scope-exclude a path** (in that order). Security findings (gitleaks) are fix-only.
- Skip one hook for one run/commit with `SKIP=<id> …` (never `--no-verify`, which disables everything).
- Roll out a new strict hook/cap at current-worst + margin, then ratchet — never a commit-blocking wall.
- Multi-language spell-check: keep `typos` on code, add `cspell` scoped to multilingual content.
