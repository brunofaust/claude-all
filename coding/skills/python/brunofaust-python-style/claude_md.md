## Python style — brunofaust-python-style

When writing or editing Python (`*.py`) files, follow the `brunofaust-python-style` skill:
- Python 3.14+ syntax: pipe unions (`str | None`), `match` statements, `asyncio.TaskGroup`, `exception.add_note()`.
- Strict type hints — `TypedDict` for structured dicts, `Literal` for constrained values, `@overload` for polymorphism. Enforced with mypy (strict) + Ruff.
- Structured logging via `structlog`.
- Settings singleton (Pydantic) — don't sprinkle `os.getenv()` calls across modules.
- Async: never block the event loop; offload blocking work via `run_in_thread()`.

If unsure about a project-specific convention not covered by the skill, ask before applying.
