## Python module migration — `python-module-migration` skill
Apply when relocating Python modules/packages and repointing imports.

Key rules: use `perl` with negative-lookbehind (not `sed` substring replace); `pytest --collect-only` catches broken imports but NOT stale `patch("old.path")` targets — grep and repoint those too. Gate: zero residual refs + collect-only green before committing. Delegate mechanical execution to `python-module-migrator` agent.
