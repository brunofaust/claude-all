# Full annotated prek.toml — merged pattern

Merge of multiple projects (e.g. myapp, my-service). Pick the sections relevant to your project and remove the rest.

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
    stages = ["pre-commit"]        # IMPORTANT: must be pre-commit only — see
    # "check-added-large-files fails in --files mode" in SKILL.md for why.
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
# Split pattern: COMMIT blocks on real issues without touching files (--no-fix,
# overrides `fix = true` in [tool.ruff]); PUSH applies the autofixes + formats.
# This keeps `git commit` from rewriting files under you while still gating it.
[[repos]]
repo = "https://github.com/astral-sh/ruff-pre-commit"
rev = "v0.15.14"
hooks = [
  {
    id = "ruff-check",
    name = "🐍 python · Check with Ruff (report-only)",
    args = ["--no-fix"],          # COMMIT: surface + block, never modify files
    types_or = ["python", "pyi"],
    stages = ["pre-commit"]
  },
  {
    id = "ruff-check",
    name = "🐍 python · Fix with Ruff (--fix)",
    args = ["--fix"],             # PUSH: apply the fixes the commit check reported
    types_or = ["python", "pyi"],
    stages = ["pre-push"]
  },
  {
    id = "ruff-format",
    name = "🐍 python · Format with Ruff",
    types_or = ["python", "pyi"],
    stages = ["pre-push"]          # formatter — defer to push, no commit-time churn
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
    stages = ["pre-push"],        # slow — run only on push, not every commit
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
#     stages = ["pre-push"]
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

# Dependency CVE audit — fast (~1s) local hooks. Trigger ONLY when the lockfile
# changes so they don't run on every commit. No upstream prek hook exists for audit.
[[repos]]
repo = "local"
hooks = [
  {
    id = "pip-audit",
    name = "🔒 security · Audit Python deps for CVEs",
    entry = "pip-audit",             # requires pip-audit installed (e.g. `uv tool install pip-audit`)
    language = "system",
    pass_filenames = false,
    files = "^(pyproject\\.toml|uv\\.lock)$"
  },
  {
    id = "npm-audit",
    name = "🔒 security · Audit JS deps for CVEs",
    entry = "npm audit --audit-level=high",
    language = "system",
    pass_filenames = false,
    files = "^package-lock\\.json$"
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

# ── Local AST enforcer (project single-ownership / visibility rules) ──────────
# A `repo = "local"` hook running your own AST checker enforces rules ruff can't
# express: each SDK imported in exactly one owner package, no raw
# `asyncio.to_thread` / `subprocess` (route through owned wrappers), module-level
# names declared via `__all__`, and a valid `__all__` import contract. Keep prek
# the single gate by adding these as local hooks rather than running a side script.
# (Checker skeleton: see the brunofaust-python-style skill's `enforcement.md`.)
# [[repos]]
# repo = "local"
# hooks = [
#   {
#     id = "skill-enforcer",
#     name = "🐍 python · Enforce single-ownership + visibility (AST)",
#     entry = "python scripts/skill_enforcer.py",
#     language = "system",
#     files = "\\.py$"
#   }
# ]

# ── Local pygrep guards (one-line bans, no script) ───────────────────────────
# A pygrep hook blocks a banned token by regex — cheaper than an AST checker when
# a substring match is enough. Always exempt the owner file that legitimately
# uses the banned API (and `scripts/**` for dev-only code).
# [[repos]]
# repo = "local"
# hooks = [
#   {
#     id = "no-asyncio-to-thread",
#     name = "🐍 python · Use run_in_thread() not asyncio.to_thread",
#     entry = "asyncio\\.to_thread",
#     language = "pygrep",
#     types_or = ["python"],
#     exclude = { glob = ["src/*/core/thread_pool.py"] }   # the owner
#   },
#   {
#     id = "no-raw-subprocess-import",
#     name = "🐍 python · Use run_exec()/run_shell() not raw subprocess",
#     entry = "^import subprocess\\b|^from subprocess\\b",
#     language = "pygrep",
#     types_or = ["python"],
#     exclude = { glob = ["src/*/core/subprocess.py", "scripts/**"] }
#   }
# ]

# ── Regression-only project gates (baseline today's debt, ratchet to zero) ───
# Local gates that grandfather existing violations via a checked-in baseline file
# and fail only on NEW ones (see the `regression-gates` skill). Worth stealing:
#   • jscpd — copy-paste detector with a `--threshold` floor (dedup, never SKIP it)
#   • raw-SQL validator — parse `text("…")` SQL with sqlglot against the schema your
#     alembic migrations build (no DB) — catches column/table drift at commit time
#   • alembic-single-head — one linear migration chain + revision-id length check
# [[repos]]
# repo = "local"
# hooks = [
#   {
#     id = "jscpd",
#     name = "🔍 duplication · Detect copy-paste",
#     entry = "npx --yes jscpd --min-tokens 60 --threshold 0.5 --reporters ai src",
#     language = "system",
#     pass_filenames = false,
#     always_run = true
#   }
# ]

# ── Docstrings ───────────────────────────────────────────────────────────────
[[repos]]
repo = "https://github.com/econchick/interrogate"
rev = "1.7.0"
hooks = [
  {
    id = "interrogate",
    name = "🐍 python · Check docstrings",
    # GOTCHA: interrogate 1.7.0 resolves a Python 3.12 hook env by default, whose
    # parser chokes on PEP 758 syntax (unparenthesized `except A, B:`) used by a
    # 3.14 codebase. Pin the hook interpreter when you hit a SyntaxError here.
    language_version = "3.14",
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

# ── semantic-consistency hook (private repo example) ─────────────────────────
[[repos]]
repo = "https://github.com/myorg/myhook"
rev = "v0.1.0"
hooks = [
  { id = "myhook", name = "🧠 semantic · myhook" }
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

# ── Optional: JS/TS dead code (knip) ─────────────────────────────────────────
# Knip finds unused exports, files, and dependencies in JS/TS projects.
# No official pre-commit hook exists — integrate as a local `system` hook.
# Requires knip installed in the project (e.g. `npm add -D knip` or `pnpm add -D knip`).
#
# ⚠️  Runs at `pre-push` (NOT `pre-commit`) — knip must traverse the full
# dependency graph and cannot operate on staged files only; too slow per-commit.
#
# Config: use `knip.json` or `knip.jsonc` at the repo root.
# Avoids creating `knip.config.ts` or adding a `"knip"` key to `package.json`.
#
# [[repos]]
# repo = "local"
# hooks = [
#   {
#     id = "knip",
#     name = "⚛️ JS/TS · Dead code / unused exports (knip)",
#     entry = "npx knip --no-progress --production --cache",
#     language = "system",
#     pass_filenames = false,
#     files = ".*\\.(ts|tsx|js|jsx|mts|cts|mjs|cjs)$",
#     stages = ["pre-push"]
#   }
# ]
#
# Minimal knip.json (use instead of knip.config.ts or package.json "knip" key):
# {
#   "entry": ["src/index.ts"],
#   "project": ["src/**/*.ts"],
#   "ignore": ["**/*.test.ts", "scripts/**"],
#   "ignoreDependencies": ["some-runtime-dep-knip-cannot-detect"]
# }

# ── Optional: Local project hooks ────────────────────────────────────────────
# `language = "system"` hooks shell out to a project script (which resolves the
# venv, runs frontend tooling, etc.). Use them for checks no upstream hook covers.
# Put the slow / cross-cutting ones on `pre-push` so they don't tax every commit.
# [[repos]]
# repo = "local"
# hooks = [
#   {
#     id = "docs-updated",
#     name = "📝 docs · Enforce doc update with code change",
#     entry = "scripts/precommit_docs.sh",
#     language = "system",
#     pass_filenames = false
#   },
#   # Architecture boundary enforcement — fails if imports cross a forbidden layer.
#   # Pairs with the python-module-migration skill (lock the layout after a move).
#   {
#     id = "import-linter",
#     name = "🏗️ architecture · Import direction check",
#     entry = "scripts/run_import_linter.sh",   # wraps `lint-imports`
#     language = "system",
#     pass_filenames = false,
#     types_or = ["python"],
#     stages = ["pre-push"]
#   },
#   # Frontend gates — wrap tsc / eslint / prettier; scoped to the frontend src tree.
#   {
#     id = "frontend-typecheck",
#     name = "⚛️ frontend · TypeScript type check",
#     entry = "scripts/run_frontend_typecheck.sh",
#     language = "system",
#     pass_filenames = false,
#     files = "^frontend/src/.*\\.(ts|tsx)$",
#     stages = ["pre-push"]
#   },
#   {
#     id = "frontend-lint",
#     name = "⚛️ frontend · ESLint (hooks, a11y, unused imports)",
#     entry = "scripts/run_frontend_lint.sh",
#     language = "system",
#     pass_filenames = false,
#     files = "^frontend/src/.*\\.(ts|tsx)$",
#     stages = ["pre-push"]
#   },
#   {
#     id = "frontend-format",
#     name = "⚛️ frontend · Prettier format check",
#     entry = "scripts/run_frontend_format_check.sh",
#     language = "system",
#     pass_filenames = false,
#     files = "^frontend/src/.*\\.(ts|tsx|css)$",
#     stages = ["pre-push"]
#   }
# ]
````

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
