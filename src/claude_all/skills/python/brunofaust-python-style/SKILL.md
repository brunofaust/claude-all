# Python Coding Style Guide (condensed)

Production-grade async Python. Async-first, strict types, immutable parameter types, docstrings everywhere (100% gate), real-infra tests (LocalStack).

This is the condensed entry point. Depth and full examples live under `references/`. Read the relevant reference file before deep work in that area.

## Core principles
1. **Python 3.14+** — pipe unions (`str | None`), `match` statements, `asyncio.TaskGroup`, `exception.add_note()`, `ExceptionGroup` / `except*`, **PEP 695** generics + type aliases (`type EntityId = str`, `def first[T](...)`, `class Stack[T]`), **PEP 758** paren-less `except ValueError, TypeError:`, **PEP 649** lazy annotations (so no `from __future__ import annotations`). The baseline makes the prek `language_version` pin **mandatory, not advisory** — PEP 695 / 758 syntax an older hook interpreter can't parse makes hooks (bandit, vulture, interrogate, local AST checkers) skip the file silently and still exit 0. → [`prek` skill](../../generic/prek/SKILL.md)
1. **Async everything** — custom functions are `async def`. Exceptions: `__init__`, `__iter__`, `__enter__`, other stdlib sync dunder methods.
1. **Immutable parameter types** — `Mapping`/`Sequence` from `collections.abc`, not `dict`/`list`, for every non-mutated parameter (not just cached function inputs/outputs). Reserve mutable concrete types for params you actually mutate.
1. **Type safety first** — full type hints, `Literal`, `@overload`, Pydantic models at boundaries. **No `TypedDict`** (static-only — validates nothing at runtime) and **no `typing.cast`** (asserts a type instead of proving one — use `Model.model_validate(...)`). Enforced via mypy (strict) + Ruff.
1. **Docstring coverage 100%** (`interrogate` gate, `fail-under = 100`) — Google-style with Args / Returns / Raises / Examples. 100 is the floor, not an aspiration: a percentage floor below 100 leaves the gate unable to say which missing docstring is acceptable, so it drifts. Carve out the genuinely-noise cases explicitly instead (`ignore-init-module`, `ignore-magic`, `ignore-setters`, `ignore-overloaded-functions`) → [`references/pyproject-toml.md`](references/pyproject-toml.md).
1. **Test everything** — `MonkeyPatch.context()` for mocks. Unit + integration (LocalStack) + class structural tests. Data tests cover the full data lifecycle.

## Wiring the gates — shipped ≠ enforced (check this ON EVERY INVOCATION)

Installing this skill copies the checkers under `checkers/` (`pydantic_contract.py`, `model_contract.py`, `lambda_event_validation.py`, `flat_test_mirror.py`, `all_contract.py`) and `regression-gates/baseline_gate.py` into place **as files**. It does **NOT** wire them into any project's `prek.toml` / `.pre-commit-config.yaml` — gate wiring is *per-project* (each repo has its own hook config, paths, allowlists, and `language_version`). A shipped-but-unwired checker enforces **nothing**: it is the exact failure this whole skill is about — *a rule in prose gets violated; a rule in a checker holds*.

An un-run checker is **prose**. **So, whenever this skill is invoked on a Python project, first verify the gates are actually wired — do not assume they are:**
1. **Enumerate what ships.** List the checker files this skill installs (glob the skill's `checkers/*.py` + `baseline_gate.py`).
2. **Check each is wired.** Grep the project's `prek.toml` **and** `.pre-commit-config.yaml` for each checker's `entry`. A checker with no hook entry is unenforced — report it, and offer to wire it (recipe → `references/enforcement.md`).
3. **Confirm it actually runs, not just that it's present.** A hook can be listed and still be a vacuous pass — see the `prek` skill's *vacuous PASS*: `prek run --all-files` only sees git-tracked files and only the pre-commit stage, and an AST hook on an older `language_version` skips files while exiting 0. "Wired" means the entry exists AND `language_version` is pinned AND both stages are green.

**Auto-improvement — a code change can mint a new gate.** New rules ship over time (this skill went from 0 checkers to 5 in one cycle), and a project may add its own. So the check is not one-time: **on each invocation, also look for checkers present as files but absent from the hook config** — newly-added or newly-installed gates that nobody wired yet. Surface them. A gate that exists on disk but in no hook is the same silent gap as a rule that was only ever written in prose.

## Table of references

| If you are… | Read |
| --- | --- |
| ... |
| **Wanting to use Python 3.14 free-thread features** | [`references/free-thread-python-3-14.md`](references/free-thread-python-3-14.md) |
| ... |

[... remainder of file unchanged]}
