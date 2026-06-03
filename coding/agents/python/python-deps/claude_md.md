### Command dispatch — dependency managers → `python-deps` (Haiku)

| Command | Agent |
|---|---|
| `uv sync/add/remove/lock/upgrade`, `uv pip compile`, `uv pip install`, `pip install/uninstall`, `poetry add/remove/update/lock/install`, `pipx install/upgrade` | `python-deps` |

Anti-patterns:

- `Bash(uv sync)` / `Bash(uv pip compile ...)` / `Bash(pip install ...)` / `Bash(poetry lock)` — resolver output is hundreds of lines. Delegate to `python-deps` and act on the one-line result or the tight conflict report.
- Do NOT route test/lint runs here: `uv run pytest` → `test-runner`; `uv run mypy`/`ruff` → `code-quality`/`lint-fixer`. `python-deps` is for installing / locking / resolving DEPENDENCIES only, not for `uv run <app/tool>`.

Note: `python-deps` runs in the project root and returns a single-line success or the resolver conflict (not the full tree). Trivial `uv --version` style checks can stay inline.
