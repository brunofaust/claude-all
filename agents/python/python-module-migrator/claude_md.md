### `python-module-migrator` (Haiku) — Python module relocation
| `git mv` + import rewrites, "move X to core/", "containment refactor", "repoint imports after the move" | `python-module-migrator` |
⛔ `Bash(git mv ...)` + `Bash(perl -i -pe 's/old/new/g' ...)` loops in main session
⛔ Dispatching `general-purpose` for large file migrations — it stops mid-batch
Note: executes a move plan only; layout decisions stay in main session.
