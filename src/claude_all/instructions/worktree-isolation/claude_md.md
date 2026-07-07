## Worktree isolation — branch before you edit

Parallel sessions on one checkout corrupt each other: editing the primary working tree on the default branch means another session sees your half-finished changes (and a tree-wide git op can wipe theirs).

- **Before the FIRST `Edit`/`Write` in a repo, verify isolation.** Check `git rev-parse --show-toplevel` + `git branch --show-current`. If you're in the primary checkout (not a linked worktree) AND on the default branch (`main`/`master`), STOP and create a per-task worktree/branch first. One worktree per task.
- **Never run tree-wide git writes in a shared repo** — `git stash`, `git checkout .`, `git reset --hard`, `git clean` discard other sessions' uncommitted work. Scope every git write to explicit paths.
- Solo repo where direct default-branch edits are fine? Opt out via the `worktree-isolation-guard` hook (`CLAUDE_ALL_ALLOW_MAIN_EDITS=1`), which otherwise pauses these edits for confirmation.
