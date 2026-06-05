## Python module migration — python-module-migration skill

When relocating Python modules / packages and repointing imports (containment refactors, `git mv` + import rewrites, splitting a module into a package), apply the `python-module-migration` skill.

- Use `perl` with a negative-lookbehind (no double-nesting), **not** `sed` substring replace; quote vars + `while IFS= read -r f`; `mkdir -p` the dest dir before `git mv`.
- `pytest --collect-only` catches broken imports but **not** stale `patch("old.path")` targets — grep + repoint those too. Check for untracked destinations after the move.
- Verify gate: zero residual references to the old path + `collect-only` green, before committing.

Delegate the mechanical execution to the `python-module-migrator` agent; lock the new layout with import-linter afterward.
