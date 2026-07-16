## prek / pre-commit — `prek` skill
Apply when setting up git hooks, debugging hook failures, or resolving findings.

Rules: prek is the single gate — never substitute individual `ruff`/`mypy` runs. Delegate to `code-quality` agent. Fix order: fix → narrow allowlist → scope-exclude (never `--no-verify`). Max 2 consecutive prek failures, then surface verbatim to user.

**A green prek is not evidence until you check WHAT it looked at.** `prek run --all-files` is not the whole gate — it is *one stage*, over *tracked files only*. A hook that silently skips its input still exits 0, so the run reports PASS while having checked nothing.

- **`git add` before you trust a run.** prek only inspects **git-tracked** files; a new untracked file is skipped and the gate passes vacuously. The tell is a hook reporting **`(no files to check) Skipped`** — read the per-hook status lines, not just the final colour.
- **`--all-files` runs only the pre-commit stage.** Pre-push hooks go unexercised until you also run `prek run --all-files --hook-stage pre-push`. Both stages must be green before claiming a change is clean.
- **A hook whose env resolves an older Python goes blind.** Anything parsing Python with the interpreter's own `ast` (bandit, vulture, interrogate, local AST checkers) silently skips files it cannot parse — and exits 0. Pin **per-hook** `language_version`; a repo-level `default_language_version` does **not** reach a hook's isolated env. Tools with their own parser (ruff, jscpd, tree-sitter) are immune — don't cargo-cult the pin.

Never report "prek passed" without having seen both stages green over staged files. → the skill's *vacuous PASS* section.
