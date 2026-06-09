### `repo-cleaner` (Haiku) — filesystem cleanup
| "empty folders", "build artifacts", "__pycache__", "node_modules", "repo is cluttered", "clean up the project" | `repo-cleaner` |
⛔ `Bash(find . -type d -name "__pycache__" -exec rm -rf {} +)` inline — skips the agent's safety checks (git tracking, ignore-file references, confirmation)
⛔ `Bash(rm -rf .some-dir)` without checking git tracking — agent runs `git ls-files` first
