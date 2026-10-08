---
name: worktree-dev-environment
description: >-
  Use when setting up or debugging a project's per-worktree development environment with
  Worktrunk (`wt`): creating `.config/wt.toml` and `.worktreeinclude`, making a fresh task
  worktree ready to run tests and commit, or fixing worktrees that share git hooks, venvs or
  local settings.
---

# Worktree development environment (Worktrunk)

Every task runs in its own git worktree, so parallel agents never share a working tree. A
worktree is only useful if it is **ready in one command**: dependencies installed, git hooks
active, local untracked files present. Worktrunk's `wt switch --create <branch>` creates the
worktree and runs the project's hooks from `.config/wt.toml`. This skill sets that up.

For the `wt` CLI itself (flags, `wt list`, `wt merge`, user config), load the `worktrunk` skill
that ships with the Worktrunk Claude Code plugin (`wt config plugins claude install`).

## Prerequisites

```bash
brew install worktrunk              # or: claude-all --all --user worktrunk
wt config shell install             # lets `wt switch` cd into the new worktree
wt config plugins claude install    # Claude Code plugin: worktrunk skill + /wt-switch-create
```

## Daily use

```bash
wt switch --create feat/my-change   # new branch + worktree from the default branch, runs hooks
wt switch --create feat/x --no-cd   # same, without changing directory (scripts, agents)
wt list                             # worktrees, branches, agent activity
wt remove                           # remove the current worktree (after its PR merged)
```

The primary checkout stays on the default branch and is never edited directly. Never let
`wt merge` push to the default branch unless the user explicitly asked for a merge.

## Set up a project

### 1. `.config/wt.toml` — committed, shared by the team

Start from [`wt.toml.example`](wt.toml.example) and keep only the steps your stack needs.

Semantics you need:

- `pre-*` hooks **block** and abort on failure; `post-*` hooks run **in the background**.
- `[[pre-start]]` / `[[post-start]]` blocks are **pipeline steps** that run in order. Keys
  inside one block run **concurrently**. A failing step stops the rest of that pipeline.
- Put anything a command in the new worktree needs immediately (dependency install, hooks
  path) in `pre-start`. Put slow or optional work (cache copy, warm builds) in `post-start`.
- Project hooks need **one-time approval** per command (saved in
  `~/.config/worktrunk/approvals.toml`). A changed command asks again. `--yes` skips the
  prompt in automation.
- Templates are available in commands: `{{ branch }}`, `{{ worktree_path }}`, `{{ repo }}`,
  `{{ branch | hash_port }}` (a stable per-branch port for dev servers).

### 2. Per-worktree git hooks — the step people miss

Worktrees share `.git/hooks`. Running `prek install` (or `pre-commit install`) in a worktree
writes the **shared** hooks with that worktree's interpreter path. Removing the worktree then
breaks commits in every other worktree. Give each worktree its own hooks directory **before**
installing hooks. This is the first `pre-start` step in the example.

### 3. `.worktreeinclude` — local files to copy

Git worktrees share history but not untracked files. `wt step copy-ignored --require-include`
copies files from the primary worktree only if they are **both gitignored and listed in
`.worktreeinclude`**. List per-user settings and caches, never secrets you can fetch from a
secret store at the point of use:

```gitignore
# .worktreeinclude — gitignored files copied into new worktrees
.claude/settings.local.json
.env.local
.mypy_cache/
```

### 4. Verify

```bash
wt switch --create chore/wt-smoke --no-cd
cd ../<repo>.chore-wt-smoke && git config --worktree core.hooksPath   # per-worktree path
uv run prek run --all-files                                            # gate works here
cd - && wt remove chore/wt-smoke
```

The worktree is ready when the gate and the test suite run from it with no manual step.

## Stack variants

| Stack | `pre-start` dependency step |
| --- | --- |
| Python (uv) | `uv sync --locked` (fails on a stale `uv.lock`, never silently re-locks) |
| Node (pnpm) | `pnpm install --frozen-lockfile` |
| Node (npm) | `npm ci` |
| Mixed | One key per stack in the same `[[pre-start]]` block, so they run concurrently |

Dev servers in parallel worktrees need distinct ports. Derive one from the branch
(`PORT={{ branch | hash_port }}`) instead of hard-coding `3000`.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Commits fail in every worktree after one was removed | Shared `.git/hooks` pointed at the removed worktree's venv | Add the per-worktree `core.hooksPath` step, re-run `prek install` in each worktree |
| Hooks did not run | Project commands not approved, or `--no-hooks` used | Re-run `wt switch` and approve, or `wt config approvals add` |
| Local settings missing in the new worktree | File not gitignored, or not in `.worktreeinclude` | It must be both |
| `uv sync --locked` fails | `uv.lock` is stale on the base branch | Fix the lockfile on the base branch; never drop `--locked` |
