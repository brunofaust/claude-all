### Command dispatch — running tests → `test-runner` (Haiku)

| Command | Agent |
|---|---|
| `pytest`, `uv run pytest`, `npm test`, `pnpm test`, `yarn test`, `vitest`, `jest`, `go test`, `cargo test` | `test-runner` |

Anti-patterns:

- `Bash(uv run pytest ...)` / `Bash(pytest ...)` / `Bash(npm test)` — pytest tracebacks and coverage tables run to hundreds of lines and burn Opus/Sonnet tokens. Delegate to `test-runner` and act on its tight pass/fail summary.
- Re-running the FULL suite inline to "check nothing broke" after an edit — the iterative edit→test loop is the single biggest source of raw test invocations. Delegate every run, not just the first.
- `Bash(cd "/path/to/worktree" && pytest ...)` — the `cd` prefix does NOT exempt it. Even inside a worktree the output is just as large; delegate to `test-runner` with the worktree path + scope in the prompt.

Note: `test-runner` is read-only — it detects the framework, runs the requested scope (all tests by default; specific files/markers if you name them), and returns total passed/failed/skipped + failed test IDs + the first useful error line per failure. It NEVER edits code/tests or rewrites test config. To WRITE tests use `test-author`; to FIX failures fix the code (main session / `lint-fixer`), then re-run via `test-runner`. A single targeted test you're actively eyeballing while debugging (`pytest path::test_x -q`) can stay inline.
