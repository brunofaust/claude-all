---
name: prek
description: >-
  Git pre-commit hook framework — covers BOTH pre-commit (the original Python tool) and prek (its
  faster, dependency-free Rust drop-in). Same hook ecosystem, hook IDs, stages, and SKIP=; prek reads
  .pre-commit-config.yaml unchanged and adds an optional prek.toml. Use when: setting up pre-commit or
  prek in a project, adding or configuring hooks, debugging hook failures (staged-file issues, --files
  mode gotchas), resolving a finding (fix / allowlist / scope-exclude a path), multi-language
  spell-check (typos + cspell), understanding the final_check.py Claude Code hook pattern, or running
  it as a CI quality gate.
disable-model-invocation: false
user-invocable: true
---

# pre-commit / prek — Git Hook Framework

> This skill covers the **pre-commit** git-hook framework and **prek**, its faster Rust drop-in.
> They share the same hooks, hook IDs, config model, stages, and `SKIP=`, so everything here applies
> to **both**. Examples are shown as `prek.toml` (TOML) but map 1:1 to `.pre-commit-config.yaml`
> (YAML) — use whichever your project has.

## prek ⇄ pre-commit — interchangeable

`prek` (j178/prek) is a dependency-free Rust reimplementation of `pre-commit`, **fully compatible with
existing `.pre-commit-config.yaml` files**, plus an optional native `prek.toml`. Same `repos → hooks`
model, same upstream hook repos, same hook IDs. Translate freely:

| Action | pre-commit (Python) | prek (Rust drop-in) |
| --- | --- | --- |
| Install the tool | `pipx install pre-commit` | `uv tool install prek` |
| Install git hooks | `pre-commit install` | `prek install` |
| Run on staged files | `pre-commit run` | `prek run` |
| Run on all files | `pre-commit run --all-files` | `prek run --all-files` |
| Run one hook on files | `pre-commit run <id> --files a b` | `prek run <id> --files a b` |
| Update hook revisions | `pre-commit autoupdate` | `prek autoupdate` |
| Skip a hook | `SKIP=<id> …` | `SKIP=<id> …` (identical) |
| Config file | `.pre-commit-config.yaml` | `.pre-commit-config.yaml` **or** `prek.toml` |

The only prek-only piece is `prek.toml` (TOML) — upstream pre-commit reads YAML only; `prek util
yaml-to-toml` converts an existing config. Throughout this skill, wherever it says `prek`, read "prek
**or** pre-commit"; wherever it shows `prek.toml`, the same keys work in `.pre-commit-config.yaml` as
YAML (`repos:` / `- repo:` / `hooks:` instead of `[[repos]]` / `hooks = [...]`).

## When to invoke

- Setting up prek in a new project
- Adding or configuring hooks
- Debugging hook failures (staged-file issues, `--files` mode gotchas)
- Running prek as part of a CI quality gate
- Understanding the `final_check.py` Claude Code hook pattern

## Table of references

Bulky recipes live under `references/`. Read the matching file before deep work in that area:

| If you are…                                                                                   | Read                                                                     |
| --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Composing or extending a project's hook config (full annotated multi-project `prek.toml` + companion `pyproject.toml` tool config) | [`references/prek-toml-template.md`](references/prek-toml-template.md)  |
| Adding an embedded-SQL-against-schema local gate (sqlglot, no database)                       | [`references/sql-schema-hook.md`](references/sql-schema-hook.md)         |
| Adding multi-language spell-check (CSpell alongside `typos`)                                  | [`references/cspell.md`](references/cspell.md)                           |

______________________________________________________________________

## What prek is NOT

- `prek` / `pre-commit` is **not** a replacement for individual tools. It **orchestrates** them.
- Never run `ruff check`, `mypy`, `eslint`, or `prettier` directly when prek/pre-commit is installed.
    Those are hooks — run `prek run --all-files` (or `pre-commit run --all-files`) instead.
- "I ran ruff and it passed" ≠ "the gate passed". Other hooks (typos, gitleaks, pyupgrade,
    markdownlint, mypy) may still fail.

______________________________________________________________________

## Installation

```bash
# Recommended — install as a uv tool (available globally, isolated env)
uv tool install prek

# Or via pipx
pipx install prek

# Verify
prek --version
```

______________________________________________________________________

## Project setup

```bash
# 1. Create prek.toml at the repo root (template: references/prek-toml-template.md)
# 2. Install git hooks (writes .git/hooks/pre-commit, commit-msg, pre-push)
prek install

# Or if prek is a dev dependency in pyproject.toml
uv run prek install
```

______________________________________________________________________

## Daily commands

```bash
# Run on all staged files (what git commit would trigger)
prek run

# Run on ALL files — use before a PR, or after adding a new hook
prek run --all-files

# With uv (when prek is a project dev dependency)
uv run prek run --all-files

# Run on specific files only (used by final_check.py hook)
prek run --files src/mymodule/foo.py src/mymodule/bar.py

# Skip a specific hook by ID (comma-separated for several)
SKIP=mypy prek run --all-files
SKIP=gitleaks,mypy prek run --all-files

# The same SKIP env var works at COMMIT time — skips the hook for ONE commit.
# Use when a pre-existing failure is unrelated to your change (then fix it separately):
SKIP=mypy git commit -m "feat: ..."
# Prefer SKIP=<id> over `git commit --no-verify`: SKIP skips ONLY the named hook(s);
# --no-verify disables EVERY hook and silently hides real failures.

# Update all hooks to their latest revisions
prek autoupdate

# Run only hooks for the commit-msg stage (e.g. commitizen)
prek run --hook-stage commit-msg

# Run only hooks for the push stage
prek run --hook-stage push
```

______________________________________________________________________

## prek.toml structure

```toml
# Global Python version (all hooks that use Python default to this)
default_language_version.python = "3.14"
# OR:
# default_language_version = { python = "python3.14" }

# Global file exclusion (applies to all hooks unless overridden)
exclude = { glob = [".claude/**", ".worktrees/**", ".venv/**"] }

# Each [[repos]] block = one source of hooks
[[repos]]
repo = "https://github.com/some-org/some-repo"
rev = "v1.2.3"            # always pin to a tag
hooks = [
  {
    id = "hook-id",
    name = "emoji · Description",          # shown in terminal output
    args = ["--arg"],                      # optional CLI args
    files = "^src/",                       # regex: only run on matching paths
    exclude = { glob = ["tests/**"] },     # glob exclusion for this hook
    types_or = ["python", "pyi"],          # file type filter
    pass_filenames = false,                # don't pass file list to entry
    stages = ["pre-commit"],               # only run at this git hook stage
    additional_dependencies = ["dep>=1"]   # extra packages for isolated env
  }
]
```

### `stages` values

| Stage        | When it runs                            |
| ------------ | --------------------------------------- |
| `pre-commit` | Every `git commit`                      |
| `commit-msg` | After editor closes for commit message  |
| `push`       | On `git push`                           |
| `manual`     | Only via `prek run --hook-stage manual` |

Hooks without `stages` run at `pre-commit` by default.

______________________________________________________________________

## Full annotated prek.toml — merged pattern

The complete annotated multi-project template (every hook repo: core checks, ruff commit/push split, mypy, markdown, typos, security + CVE audits, pygrep guards, regression gates, docstrings, dead code, optional sections) + companion `pyproject.toml` tool config →
[`references/prek-toml-template.md`](references/prek-toml-template.md). Read it whenever composing or extending a project's hook config.

______________________________________________________________________

## Rolling out a new hook or complexity cap without a backlog

Turning on a strict hook (Ruff `PLR` complexity caps, `interrogate` docstring coverage, `bandit`,
`mypy --strict`) on an existing codebase usually lights up **hundreds** of pre-existing findings and
**blocks every commit** until they're all fixed — which buries the *new* signal you actually care
about under legacy noise.

Introduce strict gates at **current-worst + a small margin**, then ratchet down:

- **Measure first.** Run the candidate rule across the repo and count findings before enabling it as
  a gate: `ruff check --select PLR0915 --statistics .` (repeat per code).
- **Select specific codes, not the blanket group.** `select = ["PLR0911","PLR0912","PLR0913","PLR0915"]`
  — NOT `select = ["PLR"]`. Blanket `PLR` enabled at tight defaults has lit 300–400+ findings in one
  shot (observed: 346 → 418) and blocked the whole team. Pick the few codes that matter.
- **Set the cap just above today's worst function**, so nothing currently passing breaks:
  ```toml
  [tool.ruff.lint.pylint]
  max-branches = 12       # current worst is 11 → 12 passes today, ratchet to 10 next quarter
  max-statements = 60
  max-args = 7
  max-returns = 7
  ```
- **Ratchet, don't bulk-fix.** Lower the caps one notch per PR/sprint; each step is a small, reviewable
  diff instead of a 400-file refactor that hides real regressions.
- **Per-file ignores for legacy hotspots** (`# ruff: noqa: PLR0915` with a TODO) beat disabling the
  rule globally — new code still gets gated.

The goal: the gate blocks *new* complexity from day one, while legacy debt is paid down on a schedule
— never a commit-blocking wall of pre-existing findings.

______________________________________________________________________

## Custom `local` checkers — author a project-specific gate

When an off-the-shelf hook can't express a rule your repo needs, write a `local` hook that runs your
own script. Wire it like vulture (a `repo = "local"` entry calling an `entry` script). Two rules keep
a custom gate honest:

- **Roll it out regression-only.** A new checker on a brownfield repo finds existing violations — seed
  a baseline and ratchet to zero rather than blocking every commit. The **`regression-gates`** skill
  ships a runnable `baseline_gate.py` harness (new findings fail, baselined pass, **stale baseline
  entries also fail** so the file only shrinks, keyed by stable identity, fail-closed) plus example
  checkers (`migration_head`, `ci_env_guard`, `junk_drawer`, `module_private`). Reuse those before
  writing your own.
- **Run it in CI too**, not just pre-commit — `--no-verify` / `SKIP=` bypass pre-commit, and a gate
  that only lives client-side gets bypassed under pressure.

### If your repo has embedded SQL: suggest an SQL-against-schema gate

For a Python+SQL codebase, a very high-value `local` hook validates embedded SQL strings against the schema folded from your migrations — no database. Full recipe (sqlglot wiring + the gotchas that break a naive build) →
[`references/sql-schema-hook.md`](references/sql-schema-hook.md). Suggest it when you see raw SQL strings in a repo that owns its migrations.

______________________________________________________________________

## Resolving a hook finding — fix, scope, or allowlist

When a hook flags something, you have **three levers**, in order of preference:

1. **Fix it** — correct the underlying issue. Always the default.
1. **Allowlist narrowly** — exempt the one word / rule code / line, at config level, when it's a
    genuine false positive (a real domain term, an intentional pattern).
1. **Scope-exclude a path** — `exclude = { glob = [...] }` on the hook, for whole directories that
    shouldn't be checked at all (generated code, i18n locale dumps, vendored files, fixtures).

A top-level `exclude = { glob = [...] }` applies to **every** hook; a per-hook `exclude` scopes to one.
For a one-off bypass use `SKIP=<id>` (see Daily commands) — that's not a real resolution, just a defer.

### Worked example — `typos`

```toml
# prek.toml — scope-exclude paths typos shouldn't scan (i18n locales, generated docs)
{ id = "typos", name = "🔍 content · Check typos",
  exclude = { glob = [
    "src/myapp/i18n/locales/**",      # translated strings — not English, not typos
    "frontend/src/i18n/locales/**",
    "docs/generated/**",              # machine-generated
    "src/myapp/email/subjects.json",
  ] } }
```

```toml
# pyproject.toml — allowlist real words/identifiers typos misreads (narrower than a path exclude)
[tool.typos.default.extend-words]
mab = "mab"            # "multi-armed bandit", not a typo of "may"
[tool.typos.default.extend-identifiers]
arange = "arange"     # numpy API (np.arange), not a typo of "arrange"
```

…and if it's an actual misspelling, just **fix the word**. Prefer fix > word-allowlist > path-exclude.

### Multi-language spell-check — `typos` (code) + CSpell (content)

`typos` / `codespell` are corrections-based and English-only; for multilingual content add dictionary-based CSpell scoped to the content paths (keep `typos` on code).
Config, dictionaries, and trade-offs → [`references/cspell.md`](references/cspell.md).

### Per-hook cheat sheet

| Hook | Fix | Allowlist (narrow) | Scope-exclude (path) |
| --- | --- | --- | --- |
| `typos` | correct spelling | `[tool.typos.default.extend-words]` / `extend-identifiers` | hook `exclude` glob (i18n, generated) |
| `ruff-check` | fix the code | `# noqa: E501` (last resort) · `[tool.ruff.lint] ignore` · `per-file-ignores` | `[tool.ruff] extend-exclude` |
| `mypy` | add/narrow types | `# type: ignore[arg-type]  # reason` (NOT bare — `python-check-blanket-type-ignore` blocks that) · `[[tool.mypy.overrides]] ignore_errors` for 3rd-party | hook `exclude` glob |
| `gitleaks` | **rotate + remove the secret** | false positive → `# gitleaks:allow` · `.gitleaksignore` (fingerprint) · `[allowlist]` regex | path in `[allowlist].paths` — **never allowlist a real secret** |
| `bandit` | fix the risk | `# nosec B101` (scoped) · `[tool.bandit] skips = ["B101"]` (e.g. assert_used in tests) | `[tool.bandit] exclude_dirs` |
| `interrogate` | add the docstring | `[tool.interrogate]` `ignore-init-method` / `ignore-magic` / `fail-under` | `[tool.interrogate] exclude = [...]` |
| `vulture` | delete dead code | used-dynamically → add to `vulture_whitelist.py` | hook `exclude` glob |
| `knip` | delete the dead export/file/dependency | `ignoreExportsUsedInFile = true` · add to `ignoreDependencies` in `knip.json` for runtime-detected deps | `ignore` patterns in `knip.json` (generated files, test fixtures) |
| `markdownlint` | fix the markdown | `--disable MD013` (rule) · `<!-- markdownlint-disable MD033 -->` inline | `--config pyproject.toml` exclusions |
| `mdformat` | let it auto-format | (it's a formatter — no per-finding allowlist) | hook `exclude` glob (generated docs) |
| `pyupgrade` | let it auto-rewrite | — | per-file `exclude` glob (generated models / SDK base needing old syntax) |
| `check-added-large-files` | don't commit the blob (Git LFS / S3 + pointer) | `args = ["--maxkb=N"]` raise the limit | path exclude |
| semantic-dedup hook (`myorg/myhook`) | extract/merge/hoist the duplicate (see `lint-fixer`) | tune the similarity threshold in its config | scope-exclude generated/dup-by-design files |

Security rule: for `gitleaks` you **fix** (rotate the leaked credential + purge it) — an allowlist is
only ever for a *false* positive (a test fixture, an example key), never to wave through a real secret.

### `check-added-large-files` fails in `--files` mode

`check-added-large-files` calls `git check-attr`, which exits 128 when there are no staged files
(e.g. when running `prek run --files <files>` outside a commit context).

**Fix:** always annotate it with `stages = ["pre-commit"]` so it only runs during actual commits:

```toml
{
  id = "check-added-large-files",
  name = "🌳 git · Block large file commits",
  args = ["--maxkb=100000"],
  stages = ["pre-commit"]   # ← required
}
```

This is a prek 0.4.1 bug — `stages = ["pre-commit"]` doesn't suppress hooks in `--files` mode
for older prek versions. If you must use `--files` mode in a hook script, filter out this failure
(see `final_check.py` pattern below).

### Staged files vs `--all-files`

`prek run` (no flags) only checks staged files. If prek reports "no files to lint", the likely cause
is that the files you edited are not staged. Stage them first: `git add <file>` or use
`prek run --all-files` to bypass the staged-file filter.

### Fix-loop discipline — 2 failures, then stop

When a hook (or `final_check.py`) fires and prek fails, you get **2 attempts** to fix +
re-stage + re-run. After **2 consecutive prek failures, STOP** — surface the verbatim
error to the user and ask for direction. Never enter an infinite retry loop.

Fix **one category per attempt**, in order: lint errors first, then format errors, then
type errors. Never mix all three in one unreviewed patch. Before diagnosing "no files to
lint", confirm `prek.toml` and every changed file are staged (see above) — don't widen
the hook scope or blame config first.

### Worktrees

Claude Code creates git worktrees under `.worktrees/` and `.claude/worktrees/`. Exclude both:

```toml
exclude = { glob = [".claude/**", ".worktrees/**"] }
```

Also exclude in hooks that resolve paths via `git rev-parse`:

```toml
{ id = "no-commit-to-branch",    stages = ["pre-commit"] }
```

(`check-added-large-files` needs the same `stages = ["pre-commit"]` annotation — see
§ *`check-added-large-files` fails in `--files` mode* above.)

### mdformat formats Python code blocks

`mdformat` also formats Python inside fenced code blocks (```` ```python ````).
Any syntax error in a Markdown file's Python example will cause mdformat to fail.
Exclude Markdown files with intentional syntax examples or pseudo-code:

```toml
{ id = "mdformat", exclude = { glob = [".claude/**", "TODO.md"] } }
```

______________________________________________________________________

## final_check.py — Claude Code hook pattern

This hook runs prek on files changed during a Claude Code session, without requiring
a `git commit`. Place in `.claude/hooks/final_check.py`.

```python
#!/usr/bin/env python3
"""Run prek on files changed during this Claude Code session."""

import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).parent.parent.parent

session_id = os.environ.get("CLAUDE_SESSION_ID", "default")
tracking_file = Path(f"/tmp/{PROJECT.name}_changes_{session_id}.txt")

if not tracking_file.exists():
    sys.exit(0)

raw = tracking_file.read_text().splitlines()
tracking_file.unlink(missing_ok=True)
all_files = {f for f in raw if f.strip() and Path(f).exists()}

# Exclude worktree paths — git check-attr resolves paths relative to the main
# repo root and exits 128 when given absolute paths from a different worktree.
files = [f for f in all_files if "/.claude/worktrees/" not in f and "/.worktrees/" not in f]
if not files:
    sys.exit(0)

result = subprocess.run(
    ["uv", "run", "prek", "run", "--files", *files],
    cwd=PROJECT,
    capture_output=True,
    text=True,
    env=os.environ,
)
if result.returncode != 0:
    combined = result.stdout + result.stderr
    lines = combined.splitlines()
    # Filter out check-added-large-files failures — it calls `git check-attr`
    # which exits 128 outside a commit context (prek 0.4.1 bug).
    # This hook is enforced correctly during real `git commit` runs.
    real_failures = [
        l for l in lines if "Failed to run hook" in l and "check-added-large-files" not in l
    ]
    if real_failures or "check-added-large-files" not in combined:
        print("prek failed on changed files. Fix and re-run.", file=sys.stderr)
        print("\n".join(lines[-50:]), file=sys.stderr)
        sys.exit(2)

sys.exit(0)
```

______________________________________________________________________

## pyproject.toml hooks configuration

The companion `[tool.*]` configuration for the hooks (ruff, mypy, markdownlint, interrogate, bandit, typos) lives at the end of [`references/prek-toml-template.md`](references/prek-toml-template.md).
