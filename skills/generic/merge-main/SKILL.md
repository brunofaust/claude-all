---
name: merge-main
description: >-
  Merge origin/main into the current branch and resolve BOTH textual and SEMANTIC conflicts — for
  parallel sessions, where one session lands work on main and another must pull it in. Calling the
  skill IS the decision to merge; it does not stop to ask for permission. A clean `git merge` (zero
  textual conflicts) can still be semantically broken: main touched a file this branch deleted,
  renamed/changed a contract this branch still calls, or removed a symbol this branch references.
  Sequence: check the incoming changes → check them semantically → merge → resolve textual conflicts →
  resolve semantic conflicts (validated by the lint/test gates) → summarize to the user. It only STOPS
  to ask when the semantic check finds huge differences or high-risk impacts (large-scale logic
  divergence, security-relevant contract changes, or a genuinely ambiguous either-side resolution).
  Use when: "pull origin main and merge it", "merge main into this branch", "sync with main", "I
  merged main in the other session — bring it in here". Orchestrator only: it sequences git plus
  existing agents/skills; it never re-implements them. For opening a PR use `/ship-pr`; for a quick
  lint+test+commit use `/ship`.
disable-model-invocation: false
user-invocable: true
---

# /merge-main — check changes + semantics → merge → resolve conflicts → summarize

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

**Calling the skill is the decision to merge.** It does not stop at a gate to ask "should I merge?" —
it merges and resolves the conflicts (textual *and* semantic), then summarizes what it did. It checks
the incoming change semantically *first* so it knows what to watch for during resolution, and **only
stops to ask when the semantic check surfaces huge differences or high-risk impacts**. It delegates
each verbose step to a focused agent/skill so this session's context stays small.

## Pre-flight (always)

```bash
git fetch origin main
MB=$(git merge-base HEAD origin/main)
git log --oneline HEAD..origin/main      # incoming commits
git diff --stat "$MB" origin/main        # incoming change surface
git status --short                        # working tree must be clean before merging
git rev-parse HEAD                        # record pre-merge HEAD so the merge can be undone
```

- If `HEAD..origin/main` is empty → stop: **"already up to date with origin/main"**.
- If the working tree is dirty → stop: commit or stash first (never merge over uncommitted work).

## Steps (run in order)

1. **Check the changes.** Preview what main brings in *before* touching the working tree, using
   `git merge-tree` (computes the would-be merge in the object store — no checkout, no index change):
   ```bash
   # `git merge-tree` exits non-zero when the merge WOULD conflict — tolerate that,
   # its output is still valid (first line = tree OID, rest = textual-conflict paths).
   MERGE_OUT=$(git merge-tree --write-tree --name-only HEAD origin/main) || true
   TREE_OID=$(printf '%s\n' "$MERGE_OUT" | head -1)            # the would-be merged tree
   CONFLICT_PATHS=$(printf '%s\n' "$MERGE_OUT" | tail -n +2)   # empty = clean textual merge
   echo "$CONFLICT_PATHS"
   ```
   Note the incoming commits and any textual-conflict paths — they feed steps 4–5. Use only
   `$TREE_OID` (never the multi-line raw output) wherever a tree-ish is needed.

2. **Check them semantically — delegate to a subagent.** This is the value-add: catch what a textual
   merge misses, *before* merging, so resolution is informed. Hand a focused subagent (a
   `general-purpose` agent, or `bug-hunter` for hot code) these read-only inputs:
   ```bash
   git diff --name-status "$MB" HEAD              # our side: D = we deleted, M/A = we changed
   git diff --name-status "$MB" origin/main       # their side: D = main deleted, M/A = main changed
   git diff --find-renames --name-status "$MB" origin/main   # renames/moves on the incoming side
   git diff "$MB" origin/main                      # what main brings in
   git diff "$MB" HEAD                              # what this branch changed
   # dangling-reference check against the would-be merged tree, no checkout needed:
   #   git grep -n "<old_symbol>" "$TREE_OID"
   ```
   The subagent classifies every conflict git would **not** flag, each with `file:line`, which side
   changed what, a severity, and a **proposed resolution**:
   - **Delete/modify** — a path in (deleted by us) ∩ (modified by them), or the reverse.
   - **Dangling reference** — main removed/renamed a symbol / export / type / config key / env var /
     route the merged tree would still reference (`git grep` it in `$TREE_OID`), or the reverse.
   - **Contradicting logic** — both sides changed related behavior in different files (changed
     signature vs. unchanged call site; changed schema/interface vs. code built on the old shape).
   - **Duplicate implementation** — both sides added the same capability in different places.

3. **Merge (no-commit).** Perform the real merge, leaving it un-finalized so resolution happens before
   the commit lands:
   ```bash
   git merge --no-ff --no-commit origin/main
   ```

4. **Resolve textual conflicts.** Resolve any conflict markers git produced (those previewed in
   step 1), choosing the correct side or combining as the code intends.

5. **Resolve semantic conflicts**, then validate. Apply the fixes for step 2's findings — re-delete a
   file main re-introduced that this branch intentionally removed (or restore one main still needs),
   update call sites for a renamed/changed contract, drop dangling references, de-duplicate parallel
   implementations. Then run the **gates** to prove the resolution holds: `lint-fixer` → `test-runner`
   → `verification-loop` (the `/ship` sequence). A red gate after resolution means a conflict is still
   unresolved — fix it (loop back) before finalizing.

6. **Finalize & summarize.** Commit the merge on the **current branch** (`git commit --no-edit`), then
   give the user a concise summary: incoming commits, textual conflicts resolved, semantic conflicts
   found + how each was resolved, gate results, and the merge SHA. **Do not push** and do **not** open
   a PR — that's a separate, explicit step (`/ship-pr`). Never force-push.

## When to STOP and ask (the only escalation)

Resolve and proceed by default. Stop and ask the user **only** when the semantic check (step 2)
surfaces something the skill should not decide alone:

- **Huge differences** — large-scale logic divergence where main and this branch reworked the same
  area in incompatible ways (not a localized conflict).
- **High-risk impact** — security-relevant contract changes (auth, secrets, permissions, tenant
  scoping), data-migration / schema changes, or anything where the wrong resolution is hard to undo.
- **Genuinely ambiguous resolution** — either side could be the intended outcome and the diff alone
  doesn't say which.

When you stop, lay out the conflict and the candidate resolutions so the user can decide without
scrolling. Nothing is force-pushed; `git merge --abort` (pre-finalize) or
`git reset --hard <pre-merge-HEAD>` (post-finalize) returns to the clean pre-merge state if they
choose not to proceed.

## Rules

- **Calling the skill is the decision to merge.** Don't re-ask whether to merge — analyze, merge,
  resolve, summarize. The only stop is the high-risk / huge-difference / ambiguous escalation above.
- **Check semantics before merging.** Steps 1–2 run with the working tree untouched (`git merge-tree`,
  ref diffs, `git grep` against the would-be tree) so resolution in steps 4–5 is informed.
- **A clean textual merge is not a clean merge.** The semantic pass always runs, even when the preview
  reports zero textual conflicts — that silent case is exactly what this skill exists for.
- **No-commit until resolved + green.** The merge uses `--no-commit`; finalize only after both kinds of
  conflict are resolved and the gates pass.
- **Targets origin/main specifically** — the parallel-session sync case. For a different base, say so.
- **Delegate, don't inline.** The semantic read and the gates each run in their own agent; one PASS/FAIL
  line per step.
- **Local merge only.** Finalize commits to the current branch; pushing and PR-opening are out of scope
  (`/ship-pr`). Never force-push or enable auto-merge from here.

## Fallback — older git without `git merge-tree --write-tree`

If `git merge-tree --write-tree` is unavailable (git < 2.38), keep the semantic check pre-merge: run
the ref diffs in step 2 against `$MB` / `origin/main` (no tree needed), and for would-be merged content
do the merge in a **throwaway worktree** so your real tree stays clean —
`git worktree add /tmp/merge-preview HEAD && git -C /tmp/merge-preview merge --no-commit origin/main`,
inspect/grep there, then `git worktree remove --force /tmp/merge-preview`. Then merge for real at step 3.

## Output

When resolved cleanly and finalized:

```
merge-main: incoming 3 commits · 1 textual conflict resolved · semantic 1 fixed (deleted-but-modified: src/myapp/handlers/foo.py → kept deletion) · lint ✓ · tests ✓ · verify READY · merge <sha>
```

When the semantic check escalates:

```
merge-main: incoming 7 commits · semantic HIGH-RISK (auth contract reworked on both sides) → STOP, awaiting decision before merge
```
