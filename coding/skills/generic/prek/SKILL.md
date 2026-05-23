# prek — Git Hook Framework

> `prek` is a Rust-based pre-commit hook runner. It uses `prek.toml` instead of `.pre-commit-config.yaml`,
> runs the same pre-commit hook ecosystem, and is significantly faster.
> This skill covers setup, daily usage, and the full annotated `prek.toml` pattern.

## When to invoke

- Setting up prek in a new project
- Adding or configuring hooks
- Debugging hook failures (staged-file issues, `--files` mode gotchas)
- Running prek as part of a CI quality gate
- Understanding the `final_check.py` Claude Code hook pattern

______________________________________________________________________

## What prek is NOT

- `prek` is **not** a replacement for individual tools. It **orchestrates** them.
- Never run `ruff check`, `mypy`, `eslint`, or `prettier` directly when prek is installed.
    Those are prek hooks — run `prek run --all-files` instead.
- "I ran ruff and it passed" ≠ "prek passed". Other hooks (typos, gitleaks, pyupgrade,
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
# 1. Create prek.toml at the repo root (see template below)
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

# Skip a specific hook by ID
SKIP=mypy prek run --all-files
SKIP=gitleaks,mypy prek run --all-files

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

Merge of multiple projects (e.g. myapp, datalake, claude-all). Pick the sections relevant to your project and remove the rest.
Pick the sections relevant to your project and remove the rest.

````toml
# ── Global ───────────────────────────────────────────────────────────────────
default_language_version.python = "3.14"   # or "3.11" for older projects

exclude = { glob = [
  ".claude/**",        # Claude Code internal files
  ".worktrees/**",     # git worktrees
  ".venv/**",          # virtualenv
  ".mypy_cache/**",
  ".pytest_cache/**",
  ".ruff_cache/**",
  "conftest.py",       # project-specific: exclude root conftest
] }

# ── Core file checks ─────────────────────────────────────────────────────────
[[repos]]
repo = "https://github.com/pre-commit/pre-commit-hooks"
rev = "v6.0.0"
hooks = [
  { id = "check-json",   name = "✅ check · Validate json files" },
  { id = "check-toml",   name = "✅ check · Validate toml files" },
  { id = "check-xml",    name = "✅ check · Validate xml files" },
  { id = "check-yaml",   name = "✅ check · Validate yaml files" },
  { id = "end-of-file-fixer",    name = "✅ check · Fix end of file" },
  { id = "trailing-whitespace",  name = "✅ check · Trailing whitespaces" },
  { id = "debug-statements",     name = "✅ check · Debug statements" },
  { id = "mixed-line-ending",    name = "✅ check · Mixed line ending" },
  { id = "check-case-conflict",  name = "📁 filesystem/📝 names · Check case sensitivity" },
  { id = "check-executables-have-shebangs", name = "📁 filesystem/⚙️ exec · Verify script permissions" },
  {
    id = "name-tests-test",
    name = "🧪 test · Validate test naming",
    args = ["--pytest-test-first"],
    files = "^tests/.+\\.py$",
    exclude = { glob = ["tests/conftest.py", "tests/**/__init__.py", "tests/local/**"] }
  },
  { id = "check-symlinks",  name = "📁 filesystem/🔗 symlink · Check symlink validity" },
  {
    id = "destroyed-symlinks",
    name = "📁 filesystem/🔗 symlink · Detect broken symlinks",
    exclude = { glob = [".git/worktrees/**", ".worktrees/**"] }
  },
  { id = "check-merge-conflict",   name = "🌳 git · Detect conflict markers" },
  { id = "forbid-new-submodules",  name = "🌳 git · Prevent submodule creation" },
  {
    id = "no-commit-to-branch",
    name = "🌳 git · Protect main branches",
    stages = ["pre-commit"]        # don't run in --files mode
  },
  {
    id = "check-added-large-files",
    name = "🌳 git · Block large file commits",
    args = ["--maxkb=100000"],
    stages = ["pre-commit"]        # IMPORTANT: must be pre-commit only
    # check-added-large-files calls `git check-attr` which exits 128 when
    # there are no staged files (e.g. in --files mode). Restrict to
    # pre-commit stage so it's skipped by final_check.py.
  }
]

# ── CRLF / tabs ──────────────────────────────────────────────────────────────
[[repos]]
repo = "https://github.com/Lucas-C/pre-commit-hooks"
rev = "v1.5.6"
hooks = [
  { id = "remove-crlf", name = "✅ check · Remove CRLF" },
  { id = "remove-tabs", name = "✅ check · Remove tabs" }
]

# ── Conventional commits ──────────────────────────────────────────────────────
# Enforces feat/fix/chore/docs/refactor/test/etc. format.
# Only runs at commit-msg stage so it doesn't block --amend or WIP pushes.
[[repos]]
repo = "https://github.com/commitizen-tools/commitizen"
rev = "v3.29.0"
hooks = [
  {
    id = "commitizen",
    name = "📝 git · Conventional commit format",
    stages = ["commit-msg"]
  }
]

# ── uv ───────────────────────────────────────────────────────────────────────
[[repos]]
repo = "https://github.com/astral-sh/uv-pre-commit"
rev = "0.11.15"
hooks = [
  { id = "uv-lock", name = "📦 uv · Lock dependencies" }
  # Optional: export requirements.txt for Snyk/pip-audit
  # {
  #   id = "uv-export",
  #   name = "📦 uv · Export dependencies",
  #   args = ["--frozen", "--output-file=requirements.txt", "--quiet",
  #           "--no-default-groups", "--no-hashes", "--no-header",
  #           "--no-annotate", "--no-editable", "--no-emit-local"]
  # }
]

# ── pyproject.toml ───────────────────────────────────────────────────────────
[[repos]]
repo = "https://github.com/abravalheri/validate-pyproject"
rev = "v0.25"
hooks = [
  {
    id = "validate-pyproject",
    name = "🐍 python · Validate pyproject.toml",
    additional_dependencies = ["validate-pyproject-schema-store[all]"]
  }
]

[[repos]]
repo = "https://github.com/tox-dev/pyproject-fmt"
rev = "v2.21.2"
hooks = [
  { id = "pyproject-fmt", name = "🐍 python · Format pyproject.toml" }
]

# ── Python upgrade ───────────────────────────────────────────────────────────
[[repos]]
repo = "https://github.com/asottile/pyupgrade"
rev = "v3.21.2"
hooks = [
  {
    id = "pyupgrade",
    name = "🐍 python · Upgrade version 3.14+",
    args = ["--py314-plus"]              # match your min Python version
  }
]

# ── Ruff (lint + format) ─────────────────────────────────────────────────────
[[repos]]
repo = "https://github.com/astral-sh/ruff-pre-commit"
rev = "v0.15.14"
hooks = [
  {
    id = "ruff-check",
    name = "🐍 python · Check with Ruff",
    args = ["--fix"],
    types_or = ["python", "pyi"]
  },
  {
    id = "ruff-format",
    name = "🐍 python · Format with Ruff",
    types_or = ["python", "pyi"]
  }
]

# ── Mypy ─────────────────────────────────────────────────────────────────────
# Option A: mirrors-mypy (isolated env, provide type stubs via additional_dependencies)
[[repos]]
repo = "https://github.com/pre-commit/mirrors-mypy"
rev = "v1.16.0"
hooks = [
  {
    id = "mypy",
    name = "🐍 python · Validate with Mypy",
    pass_filenames = false,
    stages = ["push"],        # slow — run only on push, not every commit
    additional_dependencies = [
      # add your type stubs here:
      # "types-aiobotocore[dynamodb,lambda,s3,sns,sqs]",
      # "types-PyYAML",
    ]
  }
]
# Option B: local hook (use project's own mypy + .venv)
# [[repos]]
# repo = "local"
# hooks = [
#   {
#     id = "mypy",
#     name = "🐍 python · Validate with Mypy",
#     language = "system",
#     entry = "scripts/run_mypy.sh",   # wrapper that resolves main repo .venv
#     args = ["src/"],
#     pass_filenames = false,
#     types_or = ["python", "pyi"],
#     stages = ["push"]
#   }
# ]

# ── Markdown ─────────────────────────────────────────────────────────────────
[[repos]]
repo = "https://github.com/igorshubovych/markdownlint-cli"
rev = "v0.48.0"
hooks = [
  {
    id = "markdownlint-fix",
    name = "📝 markdown · Fix markdown",
    args = [
      "--config", "pyproject.toml",
      "--configPointer", "/tool/markdownlint",
      "--disable", "MD013"
    ]
  }
]

[[repos]]
repo = "https://github.com/hukkin/mdformat"
rev = "1.0.0"
hooks = [
  {
    id = "mdformat",
    name = "📝 markdown · Format markdown",
    additional_dependencies = [
      "mdformat-ruff",
      "ruff",
      "mdformat-mkdocs"
      # "mdformat-pyproject"   # add if you use pyproject.toml for mdformat config
    ],
    exclude = { glob = [".claude/**", "TODO.md"] }
    # mdformat also formats Python code blocks in fenced fences.
    # Any syntax error in a ```python block will cause this hook to fail.
  }
]

# ── Typos ────────────────────────────────────────────────────────────────────
[[repos]]
repo = "https://github.com/crate-ci/typos"
rev = "v1.46.2"
hooks = [
  {
    id = "typos",
    name = "🔍 content · Check typos",
    exclude = { glob = [
      "tests/**",
      # add locale files, test fixtures, generated content, etc.
    ] }
  }
]

# ── Security ─────────────────────────────────────────────────────────────────
[[repos]]
repo = "https://github.com/gitleaks/gitleaks"
rev = "v8.30.1"
hooks = [
  { id = "gitleaks", name = "🔒 security · Detect secrets" }
]

[[repos]]
repo = "https://github.com/PyCQA/bandit"
rev = "1.9.4"
hooks = [
  {
    id = "bandit",
    name = "🔒 security · Detect common security issues",
    args = ["-c", "pyproject.toml"]   # reads [tool.bandit] from pyproject.toml
  }
]

# ── Python anti-patterns ─────────────────────────────────────────────────────
[[repos]]
repo = "https://github.com/pre-commit/pygrep-hooks"
rev = "v1.10.0"
hooks = [
  {
    id = "python-check-blanket-type-ignore",
    name = "🐍 python · Enforce not blanket #type: ignore",
    exclude = { glob = ["tests/**"] }
  },
  { id = "python-check-mock-methods",    name = "🐍 python · Prevent common mistakes of mocking" },
  { id = "python-no-log-warn",           name = "🐍 python · Not using deprecated log.warn" },
  { id = "python-use-type-annotations",  name = "🐍 python · Enforce type annotations not comments" },
  { id = "text-unicode-replacement-char", name = "🐍 python · Forbid UTF-8 Unicode replacement character" }
]

# ── Docstrings ───────────────────────────────────────────────────────────────
[[repos]]
repo = "https://github.com/econchick/interrogate"
rev = "1.7.0"
hooks = [
  {
    id = "interrogate",
    name = "🐍 python · Check docstrings",
    pass_filenames = false
    # configure thresholds in [tool.interrogate] in pyproject.toml
  }
]

# ── Dead code ────────────────────────────────────────────────────────────────
[[repos]]
repo = "https://github.com/jendrikseipp/vulture"
rev = "v2.16"
hooks = [
  { id = "vulture", name = "🐍 python · Detect unused code" }
  # requires vulture_whitelist.py at repo root for intentional unused symbols
]

# ── codecongruence (semantic consistency) ────────────────────────────────────
[[repos]]
repo = "https://github.com/brunofaust/codecongruence"
rev = "v0.1.0"
hooks = [
  { id = "codecongruence", name = "🧠 semantic · codecongruence" }
]

# ── Optional: Makefile linting ───────────────────────────────────────────────
# [[repos]]
# repo = "https://github.com/mrtazz/checkmake.git"
# rev = "v0.3.2"
# hooks = [
#   { id = "checkmake", name = "🐮 makefile · Lint Makefile" }
# ]

# ── Optional: Jupyter notebooks ──────────────────────────────────────────────
# [[repos]]
# repo = "https://github.com/nbQA-dev/nbQA"
# rev = "1.9.1"
# hooks = [
#   { id = "nbqa-ruff-format", name = "📓 notebook · Format with Ruff",   args = ["--fix"], additional_dependencies = ["ruff"] },
#   { id = "nbqa-ruff-check",  name = "📓 notebook · Check with Ruff",    additional_dependencies = ["ruff"] },
#   { id = "nbqa-pyupgrade",   name = "📓 notebook · Upgrade version 3.14+", args = ["--py314-plus"], additional_dependencies = ["pyupgrade"] }
# ]

# ── Optional: CloudFormation linting ─────────────────────────────────────────
# [[repos]]
# repo = "https://github.com/aws-cloudformation/cfn-lint"
# rev = "v1.48.1"
# hooks = [
#   {
#     id = "cfn-lint",
#     name = "✨ cloudformation · Lint CF files",
#     pass_filenames = false,
#     args = ["deployment/cloudformation/*.yaml", "--ignore-checks=E0000,E3031,E1156,E3033"]
#   }
# ]

# ── Optional: Local project hooks ────────────────────────────────────────────
# [[repos]]
# repo = "local"
# hooks = [
#   {
#     id = "docs-updated",
#     name = "📝 docs · Enforce doc update with code change",
#     entry = "scripts/precommit_docs.sh",
#     language = "system",
#     pass_filenames = false
#   }
# ]
````

______________________________________________________________________

## Known gotchas

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

### Worktrees

Claude Code creates git worktrees under `.worktrees/` and `.claude/worktrees/`. Exclude both:

```toml
exclude = { glob = [".claude/**", ".worktrees/**"] }
```

Also exclude in hooks that resolve paths via `git rev-parse`:

```toml
{ id = "no-commit-to-branch",    stages = ["pre-commit"] }
{ id = "check-added-large-files", stages = ["pre-commit"] }
```

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

```toml
[tool.ruff]
target-version = "py314"
line-length = 100
lint.select = ["B", "C4", "E", "F", "I", "RUF", "SIM", "UP", "W"]
lint.ignore = ["RUF001"]

[tool.mypy]
strict = true
python_version = "3.14"

[tool.markdownlint]
default = true
MD003 = { style = "atx" }
MD007 = { indent = 4 }
no-hard-tabs = true
whitespace = true
MD013 = false
MD040 = false
MD025 = false

[tool.interrogate]
fail-under = 80
ignore-init-method = true
ignore-init-module = true
ignore-magic = true
ignore-property-decorators = true
quiet = true

[tool.bandit]
exclude_dirs = ["tests", "scripts"]
skips = ["B101"]   # assert_used — OK in tests

[tool.typos]
# Add false-positive overrides:
# [tool.typos.default.extend-words]
# afterall = "afterall"
```
