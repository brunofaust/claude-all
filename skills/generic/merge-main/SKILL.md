---
name: merge-main
description: >-
  Merge origin/main into the current branch with a SEMANTIC conflict pass that runs BEFORE the merge —
  for parallel sessions, where one session lands work on main and another must pull it in safely. A
  clean `git merge` (zero textual conflicts) can still be semantically broken: main touched a file this
  branch deleted, renamed/changed a contract this branch still calls, or removed a symbol this branch
  references. Sequence: fetch origin/main → preview incoming + textual conflicts (no merge yet, working
  tree untouched) → SEMANTIC pass (delete/modify, rename/move, dangling-reference, contradicting-logic,
  all from the refs) → report & DECIDE → only then merge (no-commit) → gates (lint-fixer → test-runner
  → verification-loop) → (confirm) finalize. You decide with the conflicts in hand, before the tree is
  touched — not after. Use when: "pull origin main and merge it", "merge main into this branch", "sync
  with main", "I merged main in the other session — check it before bringing it in here". Orchestrator
  only: it sequences git plus existing agents/skills and gates on their results; it never
  re-implements them. For opening a PR use `/ship-pr`; for a quick lint+test+commit use `/ship`.
disable-model-invocation: false
user-invocable: true
---

# /merge-main — preview & semantic check (no merge) → decide → merge → gates → finalize

A `ship-pr`-style orchestrator for the one job parallel sessions get wrong: **pulling origin/main into
your branch**. Git's merge only resolves *textual* overlap. When session A lands work on main and
session B has been editing in parallel, the merge can report **zero conflicts and still be wrong** —
because the conflict is *semantic*, not textual:

- main **modified** a file this branch **deleted** (or the reverse) — git silently keeps one side.
- main **renamed / moved** a file or **changed a signature / contract / schema** this branch still
  calls at the old shape — no textual overlap, so no conflict marker, but the code is now inconsistent.
- main **removed** a symbol / export / config key / env var this branch still references (a dangling
  reference) — or this branch removed one main now depends on.
- both sides added the **same feature in different places** — a duplicate, not a conflict.

**The check runs BEFORE the merge.** The semantic analysis is pure diff-reasoning over three refs
(merge-base, your HEAD, origin/main) plus a grep of the *would-be* merged tree — none of it needs the
working tree touched. So you see the conflicts and **decide whether to merge at all** before anything
changes, instead of merging and discovering the breakage afterward. **It delegates each verbose step
to a focused agent/skill** (keeping this session's context clean) and **stops on the first hard failure
or unresolved semantic finding**.

## Pre-flight (always)

```bash
git fetch origin main
MB=$(git merge-base HEAD origin/main)
git log --oneline HEAD..origin/main      # incoming commits
git diff --stat "$MB" origin/main        # incoming change surface
git status --short                        # working tree state
```

- If `HEAD..origin/main` is empty → stop: **"already up to date with origin/main"**.
- Record the pre-merge HEAD (`git rev-parse HEAD`) — nothing below changes the working tree until
  step 4, but keep it so the eventual merge can be cleanly undone.

## Steps (run in order; the merge happens only at step 4, after you've decided)

1. **Preview the merge — NO merge, working tree untouched.** Use `git merge-tree` to compute the
   would-be merge entirely in the object store: it reports textual conflicts and hands back a merged
   tree OID you can inspect, without touching the index or working tree.
   ```bash
   # newer git (2.38+): writes the merged tree to the object DB, lists conflicts, never touches HEAD
   MERGED_TREE=$(git merge-tree --write-tree --name-only HEAD origin/main)
   echo "$MERGED_TREE"        # first line = tree OID; any following lines = conflicted paths
   ```
   - **Textual conflicts listed** → note them; git *does* catch these. They factor into the decision
     at step 3 (and you'll resolve them when you actually merge at step 4).
   - **No conflicts** → do **not** trust it yet. Continue — the semantic pass is the point of this skill.

2. **Semantic conflict pass (the core) — delegate to a subagent, still pre-merge.** This is the
   value-add: catch what step 1 missed, *before* merging. Compute the inputs and hand them to a focused
   subagent (a `general-purpose` agent, or `bug-hunter` for a deep dive on hot code) so the heavy
   reading stays out of this context. All inputs are read-only refs — nothing is merged:
   ```bash
   # files this branch deleted vs. files main changed (and the reverse) → delete/modify risk
   git diff --name-status "$MB" HEAD          # our side: D = we deleted, M/A = we changed
   git diff --name-status "$MB" origin/main   # their side: D = main deleted, M/A = main changed
   # renames/moves on the incoming side that our branch may have edited at the old path
   git diff --find-renames --name-status "$MB" origin/main
   # the two diffs themselves, for contradicting-logic analysis
   git diff "$MB" origin/main                  # what main brings in
   git diff "$MB" HEAD                          # what this branch changed
   # to check dangling references against the WOULD-BE merged tree (no checkout needed):
   #   git grep -n "<old_symbol>" "$MERGED_TREE"
   ```
   The subagent classifies, against the **would-be merged tree** (`$MERGED_TREE`), every conflict git
   did **not** flag:
   - **Delete/modify** — a path in (deleted by us) ∩ (modified by them), or the reverse. The most
     common silent break: the merge would keep main's modified file even though this branch removed it
     on purpose (or vice versa). Flag each one.
   - **Dangling reference** — main removed/renamed a function, class, export, type, config key, env
     var, or route that the merged tree would still reference (`git grep` the old name in
     `$MERGED_TREE`), or this branch removed one main's incoming code now uses.
   - **Contradicting logic** — both sides changed related behavior in *different* files so the result
     would be inconsistent (changed signature vs. unchanged call site; changed schema/interface vs.
     code built on the old shape; changed invariant or default).
   - **Duplicate implementation** — both sides added the same capability in different places.

   Return findings **verbatim** with `file:line`, which side changed what, and a severity
   (block / warn). Zero findings is a valid, common result — report it as such.

3. **Report & DECIDE — before touching anything.** Print the incoming summary, the textual-conflict
   preview (step 1), and the semantic findings (step 2). This is the decision point, and the tree is
   still clean:
   - **Block-severity semantic finding (or textual conflicts you don't want to take blindly)** →
     **stop and ask** how to proceed (default). Lay out the options so the user can decide without
     scrolling: proceed and resolve during the merge, adjust this branch first, or skip the merge
     entirely. Nothing has changed yet, so "don't merge" is a clean, free outcome.
   - **Warn-only / nothing found** → say so explicitly and proceed to step 4.

4. **Merge (no-commit) — only after the decision to proceed.** Now perform the real merge, but do
   **not** finalize, so the result can still be abandoned cleanly:
   ```bash
   git merge --no-ff --no-commit origin/main
   ```
   Resolve any textual conflicts already identified in step 1. If you decide to back out at any point:
   `git merge --abort` returns to the clean pre-merge state.

5. **Gates — run the `/ship` sequence on the merged tree:** `lint-fixer` → `test-runner` →
   `verification-loop`. These need a real merged tree, so they run here as the final safety net — a
   merge that **breaks the build or a test** confirms a semantic conflict the read-pass flagged (or
   missed). Stop on the first hard failure (same rules as `/ship`); `git merge --abort` if you back out.

6. **Finalize — (after confirm).** Only when the gates are green: show the final diff summary, get a
   one-word confirm, finalize the merge commit on the **current branch**:
   ```bash
   git commit --no-edit        # finalizes the --no-commit merge
   ```
   Finalizing the merge is the one state-changing step — confirm it. **Do not push** from here and do
   **not** open a PR; pushing/PR is a separate, explicit step (`/ship-pr`). Never force-push.

## Rules

- **Check before merge.** Steps 1–3 run with the working tree untouched (`git merge-tree`, ref diffs,
  `git grep` against the would-be tree). You decide *whether to merge* with the conflicts in hand — the
  real merge (step 4) only happens after that decision. "Don't merge" is a clean, free outcome.
- **A clean textual merge is not a clean merge.** The semantic pass always runs, even when the preview
  reports zero textual conflicts — that silent case is exactly what this skill exists for.
- **No-commit until verified.** The real merge uses `--no-commit` so a bad merge is abandoned with
  `--abort`, never half-committed. Finalize only after the gates pass.
- **Block findings are a hard stop.** Never proceed/finalize over an unresolved block-severity semantic
  finding or a red gate. Surface it and let the user decide (default: report + ask).
- **Targets origin/main specifically.** This skill merges the freshly-updated `origin/main` into your
  branch — the parallel-session sync case. For a different base, say so explicitly.
- **Delegate, don't inline.** The diff-reading and the gates each run in their own agent so this
  context stays small; stop-on-hard-fail; one PASS/FAIL line per step.
- **Local merge only.** Finalize commits to the current branch; pushing and PR-opening are out of
  scope (`/ship-pr`). Never force-push or enable auto-merge from here.

## Fallback — older git without `git merge-tree --write-tree`

If `git merge-tree --write-tree` is unavailable (git < 2.38), still keep the check pre-merge: run the
ref diffs in step 2 against `$MB` / `origin/main` (no tree needed), and for the would-be merged content
do the merge in a **throwaway worktree** so your real tree stays clean —
`git worktree add /tmp/merge-preview HEAD && git -C /tmp/merge-preview merge --no-commit origin/main`,
inspect/grep there, then `git worktree remove --force /tmp/merge-preview`. Decide, then do the real
merge in your working tree at step 4.

## Output

```
merge-main: incoming 7 commits · preview 0 textual · semantic 1 BLOCK (deleted-but-modified: src/myapp/handlers/foo.py) → STOP before merge, awaiting decision
```

or, when the pre-merge check is clean and you proceed:

```
merge-main: incoming 3 commits · preview clean · semantic ✓ (0 findings) · merged · lint ✓ · tests ✓ · verify READY · merge <sha>
```
