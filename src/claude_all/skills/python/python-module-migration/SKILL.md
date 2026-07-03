---
name: python-module-migration
description: >-
  Mechanically and safely relocate Python modules/packages and repoint every importer. Use when:
  moving a module to a new package (e.g. myapp.foo → myapp.core.foo), splitting a module into a
  package, restructuring layout (containment / move-by-subject refactors), repointing imports after
  a git mv, fixing stale patch() targets after a move, or executing a move plan across src/ + tests/.
  Covers the git mv + import-repoint + collect-only verify loop and the hard-won foot-guns (perl
  negative-lookbehind to avoid double-nesting, zsh word-split, BSD-grep substring false-positives,
  ruff-hook deleting just-added imports, untracked-destination check, patch-target drift that
  collect-only misses). Pairs with the python-module-migrator agent (the executor).
disable-model-invocation: false
user-invocable: true
---

# Python Module Migration

Moving Python modules and repointing imports is *mechanical* but *foot-gun-dense*. The danger is
never the `git mv` — it's the import rewrite: a substring false-positive, a double-nested path, a
stale `patch("old.path")` string, or an agent that stops mid-batch and leaves the tree broken.

**Decide the target layout first (that's design — Sonnet/you). Then execute the move plan with the
recipe below, or hand it to the `python-module-migrator` agent.** This skill is the recipe + the
gotchas; the agent is the executor that runs it with finish discipline.

## The move loop (per file)

```bash
SRC="src/myapp/old_mod.py"
DST="src/myapp/core/new_mod.py"
OLD="myapp.old_mod"        # dotted import path of source
NEW="myapp.core.new_mod"   # dotted import path of destination

mkdir -p "$(dirname "$DST")"        # 1. dest dir must exist or git mv misplaces the file
git mv "$SRC" "$DST"                # 2. move with history

# 3. repoint every importer (perl, look-around, \Q…\E — see gotchas)
grep -rlP "(?<![.\w])${OLD//./\\.}\b" src tests 2>/dev/null \
  | while IFS= read -r f; do
      perl -0777 -i -pe "s/(?<![.\w])\Q${OLD}\E\b/${NEW}/g" "$f"
    done
```

## Gotchas (the reason this skill exists)

### 1. Use `perl` with look-around — never plain substring replace

Plain `sed s/myapp.old/myapp.new/` matches inside longer paths and produces garbage:

- `myapp.old` matches inside `myapp.olds` or `myapp.old_helpers` → corrupts unrelated names.
- Replacing `myapp.old` → `myapp.core.old` can **double-nest**: a path already containing the new
  prefix gets rewritten twice (`myapp.core.old.sub` → `myapp.core.core.old.sub`).

Fix: `perl -0777 -i -pe "s/(?<![.\w])\Q${OLD}\E\b/${NEW}/g"` — `\Q…\E` makes `.` literal, the
`(?<![.\w])` negative-lookbehind stops partial/prefix matches, `\b` anchors the end. BSD/macOS `sed`
has no reliable look-around; perl is portable.

### 2. Quote variables; iterate with `while IFS= read -r`

Unquoted `for f in $FILES` word-splits on spaces/newlines under zsh and silently skips files. Always
`grep -rl ... | while IFS= read -r f; do ... done` and quote `"$f"`.

### 3. `collect-only` does NOT catch stale string targets

`pytest --collect-only` catches broken *imports* but not these (they only fail at runtime):

```bash
grep -rnE "(patch|setattr)\(\s*[\"']${OLD//./\\.}" tests src   # patch("old.path"), monkeypatch.setattr("old…")
grep -rn  "import_module([\"']${OLD}"  src tests               # importlib.import_module("old")
```

Also check `pyproject.toml` (`[project.scripts]`, tool config paths) and entry-point strings.
Repoint these the same way, then re-verify.

### 4. The ruff `--fix` hook fights you

A `ruff --fix` pre-commit / PostToolUse hook will isort-reorder the lines you just rewrote AND
**delete a just-added import that is momentarily unused**. Two consequences:

- Do the full perl repoint in one pass, then verify — don't rely on ruff autofix mid-move.
- When you must *hand-add* an import, add the *usage first* so the import isn't transiently unused
  when the hook fires.

### 5. Check for untracked destinations after the move

A real bug class: files moved but left untracked → a broken HEAD on commit. After moves:

```bash
git status --porcelain | grep '^??'    # destinations must NOT show here
```

Stage **explicit paths only** — never `git add -A` (it sweeps in unrelated work and untracked junk).

### 6. Finish the batch — never stop half-moved

A file moved without its importers repointed (or vice-versa) is a broken tree. Complete every move
you start; if you must do fewer, leave each completed one fully repointed + verified. `git` is your
undo if a single move can't be finished cleanly.

## Verify gate — done only when all three are green

```bash
grep -rnP "(?<![.\w])${OLD//./\\.}\b" src tests   # residual refs → MUST be empty
pytest --collect-only -q 2>&1 | tail -20          # imports resolve → 0 errors
git status --porcelain | grep '^??' || true       # no untracked destinations
```

If `collect-only` exposes a genuine **circular import** or missing symbol (the move surfaced a real
design problem, not a stale path), STOP — that's a design fix, not a repoint. Don't paper over it by
moving things back blindly.

## Optional: enforce the new boundaries

After a containment / layering move, lock the structure so it can't regress:

- **import-linter** contracts (`lint-imports`) — declare independence / layering between packages.
- **ruff `banned-api` (TID251)** — block raw imports of an SDK outside its single owner module.

These belong in the *follow-up* commit, after the moves verify green — not mixed into the move itself.

## Don't commit from inside the migration

Leave staging + commit to `git-committer` (it handles the hook's autofix-and-retry and the
`--no-restage` / `skip_hooks` cases). The migration's job ends at a green verify gate.

## Anti-patterns

| Anti-pattern | Why | Use instead |
| --- | --- | --- |
| `sed -i s/old/new/` on imports | Substring false-positives, double-nesting | `perl -0777 -pe "s/(?<![.\w])\Q…\E\b/…/g"` |
| `for f in $(grep -rl …)` | zsh word-split skips/mangles paths | `grep -rl … \| while IFS= read -r f` |
| Trusting `collect-only` alone | Misses `patch("old.path")` runtime targets | Also grep patch/setattr/import_module strings |
| `git add -A` after moves | Sweeps unrelated + untracked files | Stage explicit destination paths |
| `git mv` without `mkdir -p` dest | Misplaces file / fails | Create dest dir first |
| Dispatching `general-purpose` for a big migration | Stops mid-batch → broken tree | `python-module-migrator` (finish discipline) |
| Moving files back to "fix" a circular import the move exposed | Hides a real design problem | Resolve the cycle; the move was right |
