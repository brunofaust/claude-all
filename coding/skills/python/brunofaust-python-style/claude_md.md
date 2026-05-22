## Python style — brunofaust-python-style

When writing or editing Python (`*.py`) files, follow the `brunofaust-python-style` skill:
- Python 3.14+ syntax: pipe unions (`str | None`), `match` statements, `asyncio.TaskGroup`, `exception.add_note()`.
- Strict type hints — `TypedDict` for structured dicts, `Literal` for constrained values, `@overload` for polymorphism. Enforced with mypy (strict) + Ruff.
- Structured logging via `structlog`.
- Settings singleton (Pydantic) — don't sprinkle `os.getenv()` calls across modules.
- Async: never block the event loop; offload blocking work via `run_in_thread()`.
- **Architectural rules** (SKILL.md "Architectural rules" section + `references/`): Pydantic at trust boundaries / frozen dataclasses internally; one owner class per external system; no silent except / no `log.debug` in except; factory pattern + DI in tests; `__all__` over `_` for module-level names; `domain/features/integrations/aws_resources` layout; mandatory README/CLAUDE/ARCHITECTURE/CHANGELOG/TODO updated each commit; every rule mapped to a ruff/vulture/import-linter/skill_enforcer/prek/GH-Action enforcement.

If unsure about a project-specific convention not covered by the skill, ask before applying.
