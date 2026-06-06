### Command dispatch — repo filesystem cleanup → `repo-cleaner` (Haiku)

Trigger when the user mentions: empty folders, build artifact removal, bytecode cleanup, cache dirs,
`__pycache__`, `node_modules`, `.next`, `target/`, `dist/`, `build/`, stale worktree dirs,
"repo is cluttered", "clean up the project", or "orphaned gitignore entries".

The agent:
1. Detects repo language(s) (Python, JS/TS, Go, Rust, Java, Ruby, C/C++, PHP) and applies matching patterns
2. Removes all artifact/cache/noise dirs with one confirmation (main cleanup)
3. For dirs referenced in `*ignore` files — asks per-directory: skip / delete-only / delete+sync-ignore
4. After all local deletions, checks git origin for "ghost" dirs (committed before being gitignored);
   stages their removal with `git rm --cached` if the user confirms; never commits or pushes automatically

Anti-patterns:
- `Bash(find . -type d -name "__pycache__" -exec rm -rf {} +)` inline — `-exec {} +` silently fails
  with "argument list too long" on large repos; the agent uses `xargs -0`.
- `Bash(rm -rf .some-dir)` without verifying it is not git-tracked — the agent runs `git ls-files`
  on every candidate before touching it.
- `Bash(git rm -r --cached <dir>)` to clean up an origin ghost without first checking if the dir is
  locally tracked — the agent does the check and explains the commit/push step clearly.
- Editing `*ignore` files by hand to remove stale entries — the agent asks per-dir and only removes
  specific-path lines (never glob patterns like `*.pyc`) when the user explicitly chooses `ds`.
