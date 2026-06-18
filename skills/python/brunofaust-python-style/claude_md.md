## Python style — `brunofaust-python-style` skill
**Invoke the `brunofaust-python-style` skill (via the Skill tool) when writing or editing Python (`*.py`) files** — load it, don't just lean on the summary below. The quick rules here are a reminder, not a substitute: for any non-trivial Python work read the skill's matching `references/<topic>.md` (type-hints, error-handling, async-patterns, class-design, config, testing) before the edit.

Rule: editing `.py` → load this skill first. Skipping straight to the edit on the strength of the inline summary is the anti-pattern this prevents.

Quick rules (full set lives in the skill): Python 3.11+ syntax (pipe unions, `asyncio.TaskGroup`, `match`); strict type hints (`TypedDict`, `Literal`, `@overload`); `structlog` not `logging`; Pydantic at trust boundaries; async-first; **`contextlib.suppress(Exception)` PROHIBITED** — use narrow `except SpecificError` with explicit logging; `domain/features/integrations/aws_resources` layout.
