# Python Coding Style Guide (condensed)

Production-grade async Python. Async-first, strict types, immutable parameter types, docstrings everywhere (100% gate), real-infra tests (LocalStack). This is the condensed entry point. Depth and full examples live under `references/<topic>.md`.

## Core principles
1. **Python 3.14+** — pipe unions (`str | None`), `asyncio.TaskGroup`, `match`, PEP 695 generics/aliases, PEP 649 lazy annotations — no `from __future__ import annotations`.
2. **Async everything** — custom functions are `async def`. Exceptions: `__init__`, `__iter__`, `__enter__`, other stdlib sync dunder methods.
3. **Immutable parameter types** — `Mapping`/`Sequence` from `collections.abc`, not `dict`/`list`, for every non-mutated parameter.
4. **Type safety first** — full type hints, `Literal`, `@overload`, Pydantic models at boundaries. **No `TypedDict`** (static-only — validates nothing at runtime) and **no `typing.cast`** (asserts a type instead of proving one — use `Model.model_validate(...)`).
5. **Docstring coverage 100%** (`interrogate` gate, `fail-under = 100`) — Google-style with Args / Returns / Raises / Examples. 100 is the floor, not an aspiration: a percentage floor below 100 leaves the gate unable to say which missing docstring is acceptable, so it drifts. Carve out the genuinely-noise cases explicitly instead (`ignore-init-module`, `ignore-magic`, `ignore-setters`, `ignore-overloaded-functions`), never a nit.
6. **Test everything** — `MonkeyPatch.context()` for mocks. Unit + integration (LocalStack) + class structural tests. Data tests cover the full data lifecycle.

## Wiring the gates — shipped ≠ enforced
Installing this skill copies the checkers under `checkers/` into place as files but does **NOT** wire them into any project's `prek.toml` / `.pre-commit-config.yaml` — gate wiring is per-project. A shipped-but-unwired checker enforces nothing: it is the exact failure this whole skill is about — a rule in prose gets violated; a rule in a checker holds. An unrun checker is prose.

## Table of references
| If you are… | Read |
| --- | --- |
| Multi-tenant isolation (five planes) — boundary contracts (typed `TenantScope`, token-only org, IDOR); Postgres RLS second wall (raising `app_current_org_id()`, ENABLE+FORCE, `query_system`+coverage guard); warm-start singleton/cache leak class + taxonomy; `/tmp/{org}/{exec}/` layout + cold-start sweep; AWS ABAC/STS session tags (spike-per-service, fail-closed, billing-as-IAM) | [`references/tenant-isolation.md`](references/tenant-isolation.md) |
| Owner-class pattern for external systems (Jira, AWS, OpenAI…), ruff `banned-api` config, audit recipe | [`references/external-system-ownership.md`](references/external-system-ownership.md) |
| Module-level visibility — `__all__` over `_` prefix, vulture/ruff blind-spot fix | [`references/visibility.md`](references/visibility.md) |
| Debugging AWS dev environments — full-run → isolate → hotfix vs deploy → parallel pieces → SF splitting → verify | [`aws-debug-loop` skill](../../aws/aws-debug-loop/SKILL.md) |
| Pre-PR verification — 6-phase gate with formal PASS/FAIL report (lint → types → tests → coverage → security → diff) | [`verification-loop` skill](../../generic/verification-loop/SKILL.md) |
| Project folder layout — `domain/features/integrations/aws_resources/api/db`, per-resource files, `import-linter` contracts | [`references/project-structure.md`](references/project-structure.md) |
| Enforcement matrix — every rule → ruff code / `skill_enforcer.py` rule / prek hook / GH Action | [`references/enforcement.md`](references/enforcement.md) |
| **NEW** Using Python 3.14 `free_thread` — when to use, pros/cons, implementation, compatibility | [`references/free-thread.md`](references/free-thread.md) |

## Naming conventions
... (rest unchanged)
