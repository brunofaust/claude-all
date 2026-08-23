# brunofaust-python-style

description: >-
  Modern Python 3.14+ coding standards for async-first, type-safe production code. Use when: writing async Python code, building CDC pipelines, implementing data transformations, adding type hints, setting up pytest fixtures, designing dataclasses, reviewing code for Python best practices, optimizing async patterns, or creating data engineering features.
  Enforce for all Python coding tasks: new features, refactoring, bug fixes, type safety reviews, async/await patterns, structured logging, datalake silver/gold layer transformations.

disable-model-invocation: false
user-invocable: true

# Python Coding Style Guide (condensed)

Production-grade async Python. Async-first, strict types, immutable parameter types, docstrings everywhere (100% gate), real-infra tests (LocalStack). **This is the condensed entry point.** Depth and full examples live under `references/`. Read the relevant reference file before deep work in that area.

## Core principles

1. **Python 3.14+** — pipe unions (`str | None`), `match` statements, `asyncio.TaskGroup`, `exception.add_note()`, `ExceptionGroup` / `except*`, **PEP 695** generics + type aliases (`type EntityId = str`, `def first[T](...)`, `class Stack[T]`), **PEP 758** paren-less `except ValueError, TypeError:`, **PEEP 649** lazy annotations (so no `from __future__ import annotations`). The baseline makes the prek `language_version` pin **mandatory, not advisory** — PEP 695 / 758 syntax an older hook interpreter can't parse makes hooks (bandit, vulture, interrogate, local AST checkers) skip the file silently and still exit 0. → [`prek` skill](../../generic/prek/SKILL.md)

... (remainder of unchanged content remains as previously retrieved)

## Table of references

| If you are… | Read |
|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
| Implementing Python 3.14 free-thread patterns | [`references/free-thread-python-3.14.md`](references/free-thread-python-3.14.md)
| ... (rest of table unchanged)
