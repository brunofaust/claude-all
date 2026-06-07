## Python style — `brunofaust-python-style` skill
Apply when writing/editing Python (`*.py`) files.

Key rules: Python 3.11+ syntax (pipe unions, `asyncio.TaskGroup`, `match`); strict type hints (`TypedDict`, `Literal`, `@overload`); `structlog` not `logging`; Pydantic at trust boundaries; async-first; **`contextlib.suppress(Exception)` PROHIBITED** — use narrow `except SpecificError` with explicit logging; `domain/features/integrations/aws_resources` layout.
