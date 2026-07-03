### `code-quality` (Haiku) — lint / type-check runner (report-only)
| `ruff`, `mypy`, `eslint`, `prettier`, `tsc --noEmit`, `prek`, `pre-commit` — run gates and report findings | `code-quality` |
⛔ `Bash(ruff check ...)`, `Bash(mypy ...)`, `Bash(eslint ...)`, `Bash(prek run ...)` inline. In any project with `prek.toml` the ONLY valid lint command is `prek run --all-files` — individual tool runs bypass the chain ("ruff passed" ≠ "prek passed": typos, gitleaks, markdownlint may still fail).
Note: reports only; to FIX findings use `lint-fixer`. Full method → the `prek` skill.
