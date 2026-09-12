---
name: brunofaust-python-style
description: >-
  Use before writing, editing or reviewing Python, including tests, type contracts, async code, logging and data transformations.
disable-model-invocation: false
user-invocable: true
---

# Python Coding Style Guide (condensed)

Production-grade async Python. Async-first, strict types, immutable parameter types, docstrings everywhere (100% gate), real-infra tests (LocalStack).

**This is the condensed entry point.** Depth and full examples live under `references/`. Read the relevant reference file before deep work in that area.

## Core principles

1. **Python 3.14+** — pipe unions (`str | None`), `match` statements, `asyncio.TaskGroup`, `exception.add_note()`, `ExceptionGroup` / `except*`, **PEP 695** generics + type aliases (`type EntityId = str`, `def first[T](...)`, `class Stack[T]`), **PEP 758** paren-less `except ValueError, TypeError:`, **PEP 649** lazy annotations (so no `from __future__ import annotations`). The baseline makes the prek `language_version` pin **mandatory, not advisory** — PEP 695 / 758 syntax an older hook interpreter can't parse makes hooks (bandit, vulture, interrogate, local AST checkers) skip the file silently and still exit 0. → [`prek` skill](../../generic/prek/SKILL.md)
1. **Async everything** — custom functions are `async def`. Exceptions: `__init__`, `__iter__`, `__enter__`, other stdlib sync dunder methods.
1. **Immutable parameter types** — `Mapping`/`Sequence` from `collections.abc`, not `dict`/`list`, for every non-mutated parameter (not just cached function inputs/outputs). Reserve mutable concrete types for params you actually mutate.
1. **Type safety first** — full type hints, `Literal`, `@overload`, Pydantic models at boundaries. **No `TypedDict`** (static-only — validates nothing at runtime) and **no `typing.cast`** (asserts a type instead of proving one — use `Model.model_validate(...)`). Enforced via mypy (strict) + Ruff.
1. **Docstring coverage 100%** (`interrogate` gate, `fail-under = 100`) — Google-style with Args / Returns / Raises / Examples. 100 is the floor, not an aspiration: a percentage floor below 100 leaves the gate unable to say which missing docstring is acceptable, so it drifts. Carve out the genuinely-noise cases explicitly instead (`ignore-init-module`, `ignore-magic`, `ignore-setters`, `ignore-overloaded-functions`) → [`references/pyproject-toml.md`](references/pyproject-toml.md).
1. **Test everything** — `MonkeyPatch.context()` for mocks. Unit + integration (LocalStack) + class structural tests. Data tests cover the full data lifecycle.

## Wiring the gates — shipped ≠ enforced (check this ON EVERY INVOCATION)

Installing this skill copies the checkers under `checkers/` (`pydantic_contract.py`,
`model_contract.py`, `lambda_event_validation.py`,
`flat_test_mirror.py`,
`all_contract.py`) and `regression-gates/baseline_gate.py` into place **as files**.
It does **NOT** wire them into any project's `prek.toml` / `.pre-commit-config.yaml`
— gate wiring is *per-project* (each repo has its own hook config, paths, allowlists,
and `language_version`). A shipped-but-unwired checker enforces **nothing**: it is the
exact failure this whole skill is about — *a rule in prose gets violated; a rule in a
checker holds*. An un-run checker is prose.

**So, whenever this skill is invoked on a Python project, first verify the gates are
actually wired — do not assume they are:**

1. **Enumerate what ships.** List the checker files this skill installs (glob the
   skill's `checkers/*.py` + `baseline_gate.py`).
2. **Check each is wired.** Grep the project's `prek.toml` **and**
   `.pre-commit-config.yaml` for each checker's `entry`. A checker with no hook entry
   is unenforced — report it, and offer to wire it (recipe → `references/enforcement.md`).
3. **Confirm it actually runs, not just that it's present.** A hook can be listed and
   still be a vacuous pass — see the `prek` skill's *vacuous PASS*: `prek run
   --all-files` only sees git-tracked files and only the pre-commit stage, and an
   AST hook on an older `language_version` skips files while exiting 0. "Wired" means
   the entry exists AND `language_version` is pinned AND both stages are green.

**Auto-improvement — a code change can mint a new gate.** New rules ship over time (this
skill went from 0 checkers to 5 in one cycle), and a project may add its own. So the
check is not one-time: **on each invocation, also look for checkers present as files but
absent from the hook config** — newly-added or newly-installed gates that nobody wired
yet. Surface them. A gate that exists on disk but in no hook is the same silent gap as a
rule that was only ever written in prose. Treat "there is an unwired checker" as a
finding, not a nit.

## Table of references

Read the matching file BEFORE deep work in that area. Each is a focused reference, not a full re-implementation of the rules.

| If you are…                                                                                                                                                                                    | Read                                                                                                    |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Understanding WHY a rule exists — the real production failures behind it (silent billing, blind gates, fixtures that lie, the barrel cost, aliases, verbatim strip, strict-config seams)         | [`references/incidents.md`](references/incidents.md)                                                    |
| Writing docstrings, public APIs, package docs                                                                                                                                                  | [`references/docstrings.md`](references/docstrings.md)                                                  |
| Adding generics, Protocols, type aliases, TYPE_CHECKING decisions                                                                                                                              | [`references/type-hints.md`](references/type-hints.md)                                                  |
| Touching `try/except`, designing exception hierarchies, using `suppress()`, handling AWS / boto errors                                                                                         | [`references/error-handling.md`](references/error-handling.md)                                          |
| Designing classes — inheritance for service wrappers, DI, class attributes                                                                                                                     | [`references/class-design.md`](references/class-design.md)                                              |
| Implementing caching, TTL caches, cache invalidation                                                                                                                                           | [`references/caching.md`](references/caching.md)                                                        |
| Setting up `pyproject.toml`, project bootstrap, ruff/mypy config                                                                                                                               | [`references/pyproject-toml.md`](references/pyproject-toml.md)                                          |
| Bootstrapping a new project                                                                                                                                                                    | [`references/installation.md`](references/installation.md)                                              |
| Writing README, project docs                                                                                                                                                                    | [`references/project-docs.md`](references/project-docs.md)                                              |
| Architectural decisions — KISS, SRP, Separation of Concerns, Composition>Inheritance, Rule of Three, function size, DI, anti-patterns                                                          | [`references/architecture.md`](references/architecture.md)                                              |
| **NOT over-engineering — YAGNI, minimalism, target shapes, banned-by-default abstractions, the deletion pass, when a boundary is earned vs speculative**                                        | [`references/yagni.md`](references/yagni.md)                                                            |
| Writing/optimizing async code — TaskGroup, ExceptionGroup, `run_in_thread`, semaphores, rollback, FIFO, pagination                                                                             | [`references/async-patterns.md`](references/async-patterns.md)                                          |
| Using free-threading (disabled GIL) for CPU-bound Python workloads in Python 3.14+                                                  | [`references/free-thread-python-3.14.md`](references/free-thread-python-3.14.md)                                                    |
| Writing AWS Lambda handlers — async entry point with `uvloop.run()`, `main()` pattern                                                                                                          | See `## Lambda handlers` section below + [`references/async-patterns.md`](references/async-patterns.md) |
| Configuration management — Pydantic Settings, env var coercion, nested configs, secrets from files                                                                                             | [`references/config.md`](references/config.md)                                                          |
| Writing tests — pytest, fixtures, parametrize, mocks, LocalStack, time freezing, snapshot, **factory pattern (polyfactory/factory_boy), DI over module-global mocks, mirrored src/ structure** | [`references/testing.md`](references/testing.md)                                                        |
| E2E / integration on shared infra (multi-tenant) — isolate data vs accept shared infra, one `create_tenant` factory, sequence randomization, concurrency-capable mocks, drain-to-own queues, fail-closed channels, settings-cache timing, separate serial pass for un-scopeable global tests, flaky-fix method | [`references/e2e-testing.md`](references/e2e-testing.md)                                                |
| Choosing Pydantic (the default — even internally) vs an allowlisted `@dataclass` — trust boundaries, **why TypedDict + `cast` are banned**, required-vs-optional, shared `PYDANTIC_CONFIG` + `extra="forbid"`, verbatim-content `str_strip_whitespace`, opaque fields, **Lambda event + ECS env validation**                                                  | [`references/data-modeling.md`](references/data-modeling.md)                                            |
| Serialization across a boundary — `model_dump(mode="json")`, orjson, aliases, `exclude_none`, round-trip proof                                                                                 | [`references/serialization.md`](references/serialization.md)                                            |
| Scoped global processes — run-for-one(/group) parameter on all-tenant jobs, DynamoDB idempotency that includes the scope, global-run-supersedes-customer-run rule                              | [`references/scoped-processes.md`](references/scoped-processes.md)                                      |
| Multi-tenant isolation (five planes) — boundary contracts (typed `TenantScope`, token-only org, IDOR); Postgres RLS second wall (raising `app_current_org_id()`, ENABLE+FORCE, `0` sentinel, `query_system`+coverage guard); warm-start singleton/cache leak class + taxonomy; `/tmp/{org}/{exec}/` layout + cold-start sweep; AWS ABAC/STS session tags (spike-per-service, fail-closed, billing-as-IAM)                                                                                                                       | [`references/tenant-isolation.md`](references/tenant-isolation.md)                                      |
| Owner-class pattern for external systems (Jira, AWS, OpenAI…), ruff `banned-api` config, audit recipe                                                                                          | [`references/external-system-ownership.md`](references/external-system-ownership.md)                    |
| Module-level visibility — `__all__` over `_` prefix, vulture/ruff blind-spot fix                                                                                                               | [`references/visibility.md`](references/visibility.md)                                                  |
| Debugging AWS dev environments — full-run → isolate → hotfix vs deploy → parallel pieces → SF splitting → verify                                                                               | [`aws-debug-loop` skill](../../aws/aws-debug-loop/SKILL.md)                                             |
| Pre-PR verification — 6-phase gate with formal PASS/FAIL report (lint → types → tests → coverage → security → diff)                                                                            | [`verification-loop` skill](../../generic/verification-loop/SKILL.md)                                   |
| Project folder layout — `domain/features/integrations/aws_resources/api/db`, per-resource files, `import-linter` contracts                                                                     | [`references/project-structure.md`](references/project-structure.md)                                    |
| Enforcement matrix — every rule → ruff code / `skill_enforcer.py` rule / prek hook / GH Action                                                                                                 | [`references/enforcement.md`](references/enforcement.md)                                                |
| Reference hook config — a complete, commented `prek.toml` wiring every gate above (repo hygiene + Python toolchain + this skill's `checkers/`). Copy it to your repo root **and rename it to `prek.toml`** | [`prek.toml.example`](prek.toml.example)                                                                |

## Naming conventions

| Element             | Convention                | Examples                            |
| ------------------- | ------------------------- | ----------------------------------- |
| Classes             | `PascalCase`              | `StorageClient`, `EventProcessor`   |
| Type aliases (PEP 695) | `PascalCase`           | `type EntityId = str`, `type AsyncHandler = ...` |
| Type parameters (PEP 695) | single capital        | `def first[T](...)`, `class Stack[T]` |
| Functions / methods | `snake_case`              | `get_entity_info`, `prepare_output` |
| Private methods     | leading underscore        | `_validate_keys`                    |
| Constants           | `UPPER_SNAKE_CASE`        | `CACHE_1_HOURS`, `CONFIG_BUCKET`    |
| Private attributes  | leading underscore        | `_client`, `_keys`                  |
| Parameters          | `snake_case`              | `table_name`, `primary_key_name`    |
| Worker functions    | `_name_do` suffix         | `_batch_delete_do`                  |
| Cache variables     | `function_name_cache`     | `get_data_cache`                    |
| Test files (flat mirror) | `test_<src path with / -> _>` | `test_core_aws_s3.py`, `test_features_pii_detection_service.py` |
