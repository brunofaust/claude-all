## Python style — `brunofaust-python-style` skill

Invoke the `brunofaust-python-style` skill (via the Skill tool) when writing or editing Python (`*.py`) files — load it, don't just lean on the summary below. The quick rules here are a reminder, not a substitute: for any non-trivial Python work read the skill's matching `references/<topic>.md` (type-hints, error-handling, async-patterns, class-design, config, testing, free-thread-python314) before the edit. Rule: editing `.py` → load this skill first. Skipping straight to the edit on the strength of the inline summary is the anti-pattern this prevents.

Quick rules (full set lives in the skill):
Python 3.14+ syntax (pipe unions, `asyncio.TaskGroup`, `match`, PEP 695 generics/aliases, PEP 649 lazy annotations — no `from __future__ import annotations`); strict type hints (`Literal`, `@overload`); `structlog` not `logging`; async-first; **`contextlib.suppress(Exception)` PROHIBITED** — use narrow `except SpecificError` with explicit logging; `domain/features/integrations/aws_resources` layout.

**A `dict` never carries a contract.** `TypedDict` and `typing.cast` are **BANNED**: a TypedDict validates nothing at runtime, so `cast(row_dtype, dict(row))` is a no-op that only pretends to type while mypy stays green. Every payload crossing a boundary is a Pydantic model with `extra="forbid"`.

### Free-thread Python 3.14 Reminder
For CPU-bound workloads (e.g., Polars operations, data transformations), consider using `concurrent.futures.InterpreterPoolExecutor` for true parallelism. Ensure dependencies are compatible and tasks are stateless.

The bug class is **not** the `.get(k, default)` spelling — that is a symptom. It is **a default on a field that is required**. → `references/data-modeling.md`

| Gate / symptom | Fix | ❌ Never |
| ------------------------------------------------- |------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `extra-forbid`, or a `ValidationError` on an unknown key | The key was renamed or the schema moved — update the code. A schema change **must** force a code change. | **relax to `extra="ignore"`** (or `"allow"`). The unknown key silently vanishes and you learn nothing — that re-arms the exact bug the model was added to catch. |
