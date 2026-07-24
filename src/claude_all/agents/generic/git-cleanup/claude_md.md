### `git-cleanup` (Haiku) — end-of-session repo cleanup
| "session cleanup", "clean up branches/worktrees", "too many branches/worktrees", "end of session" | `git-cleanup` |
Read-mostly branch/worktree REPORT → `git-audit`; filesystem cruft (build artifacts, `__pycache__`) → `repo-cleaner`.
Note: reconciles every "has changes" item against `origin/main` (squash-merge aware via `git merge-tree`) — worktrees/branches whose uncommitted or unpushed content is already in main are deleted (`--force`/`-D`); only items with a REAL diff vs main are reported. Force ops are licensed ONLY by that content-in-main proof.
⛔ `Bash(git branch -d ...)`, `Bash(git worktree remove ...)` chained in main session — agent runs a safety scan first.
