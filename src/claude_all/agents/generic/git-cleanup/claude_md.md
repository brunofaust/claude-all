### `git-cleanup` (Haiku) — end-of-session repo cleanup
| "session cleanup", "clean up branches/worktrees", "too many branches/worktrees", "end of session" | `git-cleanup` |
Read-mostly branch/worktree REPORT → `git-audit`; filesystem cruft (build artifacts, `__pycache__`) → `repo-cleaner`.
⛔ `Bash(git branch -d ...)`, `Bash(git worktree remove ...)` chained in main session — agent runs a safety scan first.
