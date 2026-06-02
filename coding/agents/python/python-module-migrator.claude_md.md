### Command dispatch — Python module relocation → `python-module-migrator` (Haiku)

| Task | Agent |
|---|---|
| `git mv` a module/package + repoint every importer + verify `pytest --collect-only` | `python-module-migrator` |
| Bulk `perl -i`/`sed -i` import-path rewrites across `src/` + `tests/` | `python-module-migrator` |
| "move X to core/", "containment refactor", "execute this move plan", "repoint imports after the move" | `python-module-migrator` |

Anti-patterns:
- `Bash(git mv ... )` followed by `Bash(perl -0777 -i -pe 's/old.path/new.path/g' ...)` loops in the
  main session — delegate the whole move plan to `python-module-migrator`. These loops are mechanical,
  repetitive, token-heavy, and riddled with foot-guns (zsh word-split, BSD-grep substring false
  positives, double-nesting, stale `patch("old.path")` strings, ruff-hook deleting just-added imports).
- `Bash(grep -rlE 'old.module' ... | while read f; do perl ... done)` — same; the residual-ref +
  repoint loop belongs in the agent, which finishes the batch and proves `collect-only` is green.
- Dispatching `general-purpose` for a large file migration — it stops mid-batch and leaves the tree
  half-moved + broken. `python-module-migrator` has finish discipline (every move completed + verified,
  or the batch reported BLOCKED verbatim).

The agent EXECUTES a move plan — it does NOT design the target layout (Sonnet/main session decides
where modules live) and does NOT refactor code logic (use `python-refactorer`). It never commits;
hand the green result to `git-committer`. Pairs with the `python-module-migration` skill (the recipe
+ gotchas it operates from).
