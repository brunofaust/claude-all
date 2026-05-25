### Command dispatch — git inspection → `git-runner` (Haiku)

| Command | Agent |
|---|---|
| `git log`, `git diff`, `git blame`, `git show` | `git-runner` |

Anti-patterns:
- `Bash(git log ...)` / `Bash(git diff ...)` / `Bash(git blame ...)` — these produce hundreds to thousands of lines; delegate to `git-runner`.
- `Bash(cd "/path/to/worktree" && git log ...)` / `Bash(cd "..." && git diff ...)` — the `cd` prefix does NOT exempt these from delegation. Even inside a worktree, git log/diff/blame output is just as large; delegate to `git-runner` with the worktree path in the prompt.

Note: small, single-line git commands (`git rev-parse HEAD`, `git branch --show-current`, `git status` on a clean repo) are fine in the main session.
