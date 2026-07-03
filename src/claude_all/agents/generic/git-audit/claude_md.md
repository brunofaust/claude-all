### `git-audit` (Haiku) — branch / worktree audit
| "audit the repo", "which branches can I delete", "stale branches", "worktree overview", "what's the branch state" | `git-audit` |
Categorizes branches MERGED / OPEN-PR / ACTIVE-WORKTREE / UNMERGED-WORK / STALE-REMOTE-GONE before touching anything; deletions only as an audited follow-up with explicit confirmation.
End-of-session batch cleanup → `git-cleanup`; filesystem cruft (build artifacts, `__pycache__`) → `repo-cleaner`.
