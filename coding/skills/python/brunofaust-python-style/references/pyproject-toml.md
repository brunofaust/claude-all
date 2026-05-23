# pyproject.toml — project configuration

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

### Project Configuration (pyproject.toml)

Centralize all tool configuration in `pyproject.toml`. This is the single source of truth
for Ruff, mypy, and project metadata.

```toml
[tool.ruff]
line-length = 120
target-version = "py314"

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort
    "B",    # flake8-bugbear
    "C4",   # flake8-comprehensions
    "UP",   # pyupgrade
    "SIM",  # flake8-simplify
    "ASYNC",# flake8-async (detect blocking calls in async)
    "S",    # flake8-bandit (security)
]
ignore = ["E501"]  # Line length handled by formatter

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.ruff.lint.isort]
known-first-party = ["app"]

[tool.mypy]
python_version = "3.14"
strict = true
warn_return_any = true
warn_unused_ignores = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
no_implicit_optional = true

[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false
```

Run with:

```bash
uv run ruff check --fix .  # Lint and auto-fix
uv run ruff format .       # Format code
uv run mypy .              # Type check
```
