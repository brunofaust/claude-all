---
name: brunofaust-python-style
description: >-
  Modern Python 3.11+ coding standards for async-first, type-safe production code. Use when: writing async Python code, building CDC pipelines, implementing data transformations, adding type hints, setting up pytest fixtures, designing dataclasses, reviewing code for Python best practices, optimizing async patterns, or creating data engineering features. Enforce for all Python coding tasks: new features, refactoring, bug fixes, type safety reviews, async/await patterns, structured logging, datalake silver/gold layer transformations.
disable-model-invocation: false
user-invocable: true
---

# Python Coding Style Guide (condensed)

Production-grade async Python. Async-first, strict types, immutable parameter types, docstrings everywhere (≥90% gate), real-infra tests (LocalStack).

**This is the condensed entry point.** Depth and full examples live under `references/`. Read the relevant reference file before deep work in that area.

## Core principles

1. **Python 3.11+** — pipe unions (`str | None`), `match` statements, `asyncio.TaskGroup`, `exception.add_note()`, `ExceptionGroup` / `except*`.
1. **Async everything** — custom functions are `async def`. Exceptions: `__init__`, `__iter__`, `__enter__`, other stdlib sync dunder methods.
1. **Immutable parameter types** — `Mapping`/`Sequence` from `collections.abc`, not `dict`/`list`, for every non-mutated parameter (not just cached function inputs/outputs). Reserve mutable concrete types for params you actually mutate.
1. **Type safety first** — full type hints, `TypedDict`, `Literal`, `@overload`. Enforced via mypy (strict) + Ruff.
1. **Docstring coverage ≥ 90%** (interrogate gate; aim for 100%) — Google-style with Args / Returns / Raises / Examples.
1. **Test everything** — `MonkeyPatch.context()` for mocks. Unit + integration (LocalStack) + class structural tests. Data tests cover the full data lifecycle.

## Table of references

Read the matching file BEFORE deep work in that area. Each is a focused reference, not a full re-implementation of the rules.

| If you are…                                                                                                                                                                                    | Read                                                                                                    |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Writing docstrings, public APIs, package docs                                                                                                                                                  | [`references/docstrings.md`](references/docstrings.md)                                                  |
| Adding generics, Protocols, type aliases, TYPE_CHECKING decisions                                                                                                                              | [`references/type-hints.md`](references/type-hints.md)                                                  |
| Touching `try/except`, designing exception hierarchies, using `suppress()`, handling AWS / boto errors                                                                                         | [`references/error-handling.md`](references/error-handling.md)                                          |
| Designing classes — inheritance for service wrappers, DI, class attributes                                                                                                                     | [`references/class-design.md`](references/class-design.md)                                              |
| Implementing caching, TTL caches, cache invalidation                                                                                                                                           | [`references/caching.md`](references/caching.md)                                                        |
| Setting up `pyproject.toml`, project bootstrap, ruff/mypy config                                                                                                                               | [`references/pyproject-toml.md`](references/pyproject-toml.md)                                          |
| Bootstrapping a new project                                                                                                                                                                    | [`references/installation.md`](references/installation.md)                                              |
| Writing README, CHANGELOG, project docs                                                                                                                                                        | [`references/project-docs.md`](references/project-docs.md)                                              |
| Architectural decisions — KISS, SRP, Separation of Concerns, Composition>Inheritance, Rule of Three, function size, DI, anti-patterns                                                          | [`references/architecture.md`](references/architecture.md)                                              |
| Writing/optimizing async code — TaskGroup, ExceptionGroup, `run_in_thread`, semaphores, rollback, FIFO, pagination                                                                             | [`references/async-patterns.md`](references/async-patterns.md)                                          |
| Writing AWS Lambda handlers — async entry point with `uvloop.run()`, `main()` pattern                                                                                                          | See `## Lambda handlers` section below + [`references/async-patterns.md`](references/async-patterns.md) |
| Configuration management — Pydantic Settings, env var coercion, nested configs, secrets from files                                                                                             | [`references/config.md`](references/config.md)                                                          |
| Writing tests — pytest, fixtures, parametrize, mocks, LocalStack, time freezing, snapshot, **factory pattern (polyfactory/factory_boy), DI over module-global mocks, mirrored src/ structure** | [`references/testing.md`](references/testing.md)                                                        |
| E2E / integration on shared infra (multi-tenant) — isolate data vs accept shared infra, one `create_tenant` factory, sequence randomization, concurrency-capable mocks, drain-to-own queues, fail-closed channels, settings-cache timing, separate serial pass for un-scopeable global tests, flaky-fix method | [`references/e2e-testing.md`](references/e2e-testing.md)                                                |
| Choosing between Pydantic / dataclass / TypedDict — trust boundaries, internal contracts, test fixtures, **Lambda event + ECS env validation**                                                  | [`references/data-modeling.md`](references/data-modeling.md)                                            |
| Scoped global processes — run-for-one(/group) parameter on all-tenant jobs, DynamoDB idempotency that includes the scope, global-run-supersedes-customer-run rule                              | [`references/scoped-processes.md`](references/scoped-processes.md)                                      |
| Database tenant isolation (optional) — Postgres RLS (enforcing) + non-blocking audit table, session-tenant via `SET LOCAL`, per-tenant-role vs GUC injection vectors, no-code-change e2e for real lambdas                                                                                                                       | [`references/tenant-isolation.md`](references/tenant-isolation.md)                                      |
| Owner-class pattern for external systems (Jira, AWS, OpenAI…), ruff `banned-api` config, audit recipe                                                                                          | [`references/external-system-ownership.md`](references/external-system-ownership.md)                    |
| Module-level visibility — `__all__` over `_` prefix, vulture/ruff blind-spot fix                                                                                                               | [`references/visibility.md`](references/visibility.md)                                                  |
| Debugging AWS dev environments — full-run → isolate → hotfix vs deploy → parallel pieces → SF splitting → verify                                                                               | [`aws-debug-loop` skill](../../aws/aws-debug-loop/SKILL.md)                                             |
| Pre-PR verification — 6-phase gate with formal PASS/FAIL report (lint → types → tests → coverage → security → diff)                                                                            | [`verification-loop` skill](../../generic/verification-loop/SKILL.md)                                   |
| Project folder layout — `domain/features/integrations/aws_resources/api/db`, per-resource files, `import-linter` contracts                                                                     | [`references/project-structure.md`](references/project-structure.md)                                    |
| Enforcement matrix — every rule → ruff code / `skill_enforcer.py` rule / prek hook / GH Action                                                                                                 | [`references/enforcement.md`](references/enforcement.md)                                                |

## Naming conventions

| Element             | Convention                | Examples                            |
| ------------------- | ------------------------- | ----------------------------------- |
| Classes             | `PascalCase`              | `StorageClient`, `EventProcessor`   |
| Functions / methods | `snake_case`              | `get_entity_info`, `prepare_output` |
| Private methods     | leading underscore        | `_validate_keys`                    |
| Constants           | `UPPER_SNAKE_CASE`        | `CACHE_1_HOURS`, `CONFIG_BUCKET`    |
| Private attributes  | leading underscore        | `_client`, `_keys`                  |
| Parameters          | `snake_case`              | `table_name`, `primary_key_name`    |
| Worker functions    | `_name_do` suffix         | `_batch_delete_do`                  |
| TypedDicts          | `snake_case_dtype` suffix | `entity_info_dtype`                 |
| Cache variables     | `function_name_cache`     | `get_data_cache`                    |

## Import organization

Three groups, blank line between each:

```python
# 1. Standard library
import os
from collections.abc import Mapping, Sequence
from typing import Any, Literal, overload

# 2. Third-party
import cachebox
import orjson
import polars as pl

# 3. Local
from app import CACHE_1_HOURS
```

Rules: parenthesised imports for large groups, `TYPE_CHECKING` for type-only imports, **never** wildcard imports, **use** `from __future__ import annotations` for deferred, zero-cost annotations (PEP 563) on the 3.11–3.13 baseline — it becomes redundant once the project is on 3.14+ (PEP 649 makes annotations lazy by default). **Never alias an import to a `_`-prefixed name** (e.g. `import orjson as _orjson`) — module-level names never start with `_` (that's what `__all__` is for, see Visibility rule), and an alias must *mean something* (disambiguation, convention like `import polars as pl`), not act as a visibility hack. If you're aliasing to hide a name, you want `__all__` instead.

Full TYPE_CHECKING semantics + Protocol typing + generics → `references/type-hints.md`.

## Modern Python idioms (3.11+)

```python
# Dict merging
enriched = item | {"source_info": info}

# Set ops on dict keys
all_keys = entity["keys"].keys() | entity.get("alt_keys", {}).keys()

# Walrus where it improves readability
if (result := await get_data()) is not None:
    process(result)

# f-strings for all formatting
logging.info(f"Loaded df: {round(df.estimated_size('mb'), 2)} MB")

# Polars lazy chains
lf = df.lazy().filter(pl.col("active").eq(True)).select(["id", "name"])
```

Multiple exceptions in one except: `except (ValueError, TypeError):` (parenthesised tuple). PEP 758's paren-less form (`except ValueError, TypeError:`) is 3.14+ only. See `references/error-handling.md`.

## Preferred libraries

| Purpose              | Use             | Never                         |
| -------------------- | --------------- | ----------------------------- |
| DataFrames           | **Polars**      | pandas                        |
| JSON                 | **orjson**      | stdlib `json`                 |
| Event loop           | **uvloop**      | default asyncio loop          |
| Hashing (non-crypto) | **xxhash**      | hashlib                       |
| AWS SDK              | **aiobotocore** | sync `boto3` in async code    |
| Caching              | **cachebox**    | `functools.lru_cache`         |
| Logging              | **structlog**   | stdlib logging with f-strings |
| Dependencies         | **uv**          | pip                           |

## Lambda handlers

Every Lambda handler must be **async-first**. The sync `handler` is a one-line wrapper that calls `uvloop.run()` — never `asyncio.run()`, never business logic inside.

```python
import uvloop
from typing import Any
from pydantic import BaseModel


class HandlerEvent(BaseModel):
    """Validated entry payload — parse the untrusted `event` dict here, once."""

    model_config = {"extra": "forbid", "frozen": True}

    run_date: str


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS Lambda entry point — sync shell, async body."""
    return uvloop.run(main(event))


async def main(event: dict[str, Any]) -> dict[str, Any]:
    """Async implementation — validate at the boundary, then run typed logic."""
    parsed = HandlerEvent.model_validate(event)  # boundary parse — raises on bad shape
    ...
```

Rules:

- `lambda_handler` is **sync** (AWS requirement) — one line only: `return uvloop.run(main(event))`.
- `main()` is `async def` and contains all business logic.
- **Validate the payload at the boundary.** The `event` dict (and any SQS/SNS/EventBridge record, Step Functions input, or ECS env block) is untrusted shape — parse it into a Pydantic model as the first line of `main()`, before any logic. ECS tasks validate their env vars through a `pydantic-settings` model at startup. → [`references/data-modeling.md`](references/data-modeling.md)
- Never call `asyncio.run()` — always `uvloop.run()`.
- Never put business logic inside `lambda_handler`.

Full event loop patterns → [`references/async-patterns.md`](references/async-patterns.md).

## Code organisation

Section headers for long files:

```python
################################################################################
# Configuration
################################################################################

# ... config code

################################################################################
# Data Processing
################################################################################
```

## Architectural rules (one-liners — depth in references)

1. **Data modeling.** Pydantic at trust boundaries, frozen dataclasses internally, TypedDict only for static test data. Never pass `dict[str, Any]` between modules. **Every entry point validates its payload** — Lambda events (SQS/SNS/EventBridge/Step Functions/direct invoke) and ECS env vars (`pydantic-settings`) are parsed into a Pydantic model at the boundary, before any logic. → `references/data-modeling.md`
1. **External system ownership.** One owner class per external system (Jira, S3, OpenAI, …). All SDK / HTTP calls flow through it; ruff `banned-api` blocks raw imports outside owner folders. → `references/external-system-ownership.md`
1. **Error handling discipline.** No silent except. No `log.debug` inside `except`. Catch narrowest class, log at `warning`/`error` with structured context, `raise ... from e` when converting. **`contextlib.suppress(Exception)` is strictly prohibited** — it silences all exceptions including bugs and OOM; `suppress(SpecificError)` requires explicit justification. → `references/error-handling.md`
1. **Test patterns.** Use factories (polyfactory / factory_boy). Never `mod._client = mock` (race-prone under xdist) — inject the dependency. Tests mirror `src/` 1:1. **Test data is isolated**: dynamic DB ids (never hard-coded), each test owns its own rows (nothing shared), FKs never cross tenants, suite runs under `pytest-xdist` (concurrency *is* the isolation check). **No `@pytest.mark.xdist_group`** to prop up co-dependent tests — make each test self-contained; the marker is a rare, user-approved, documented exception only. → `references/testing.md`
1. **Scoped global processes.** Every all-tenant job (Lambda/ECS) accepts an optional scope to run for one entity or a group — one code path (`scope or list_all()`), absent scope = global. DynamoDB idempotency includes the scope: a global run **supersedes** a customer-scoped run (the customer claim is blocked when a global run already covers it). Enables both e2e test isolation and single-customer production re-runs. → `references/scoped-processes.md`
1. **Visibility.** Module-level names never start with `_` — use `__all__`. Class-scope `self._x` is fine. The `_`-prefix blinds vulture, ruff, pyright to dead-code at module scope. → `references/visibility.md`
1. **Project structure.** `domain/` (pure logic) → `features/` (vertical slices) → `integrations/` + `aws_resources/` + `db/` (horizontal). Entry points (`api/`, `cli/`, lambdas) stay thin. Enforce direction with `import-linter`. → `references/project-structure.md`
1. **Documentation discipline.** Every code change ships with doc update. Mandatory files: README, CLAUDE.md (root + per resource), ARCHITECTURE, CHANGELOG, TODO. Prek hooks + GH Actions block merge if docs stale. → `references/project-docs.md`
1. **No hardcoded config values.** Nothing that could change between environments, deployments, or over time may be hardcoded at module or class level. LLM model names, Jira/workflow statuses, S3/SQS/SNS resource names, API endpoints, timeouts, batch sizes, feature flags → all go in `Settings`. The only exception: *function/method parameter defaults* (they're explicit call-site overrides, not hidden globals). `os.getenv()` outside `Settings` is also banned. → `references/config.md`
1. **Enforcement.** Every rule maps to ruff code / vulture / `import-linter` / `skill_enforcer.py` AST rule / prek hook / GH Action. No aspirational rules. → `references/enforcement.md`

## Quick rules — What NOT to do

### Libraries / tools

- ❌ `dict`/`list` as parameter or cached-return types → use `Mapping`/`Sequence`.
- ❌ Sync custom logic functions (only stdlib dunders are sync).
- ❌ `@pytest.mark.asyncio` → `conftest.py` handles it.
- ❌ Mocking AWS in integration tests → LocalStack.
- ❌ `asyncio.run()` → `uvloop.run()`.
- ❌ Business logic inside `lambda_handler` — sync handler is one line: `return uvloop.run(main(event))`, all logic in `async def main()`.
- ❌ Wildcard imports.
- ❌ Global mutable state → pass context objects.
- ❌ Dropping `from __future__ import annotations` on the 3.11–3.13 baseline — keep it for deferred annotations (PEP 563); it's only redundant on 3.14+ (PEP 649).
- ❌ Committing secrets / API keys.

### Architecture

- ❌ Scattered retry / timeout logic — centralise in decorators / client wrappers.
- ❌ Retry at multiple layers (app + client lib) — pick ONE.
- ❌ **Hardcoded config at module or class level** — any value that could differ between environments or change over time must live in `Settings`, env var, or be passed as a parameter. Covers: LLM model names, Jira/workflow statuses, S3/SQS/SNS resource names, API endpoints, timeouts, batch sizes, feature flags. Function/method *parameter defaults* are the one allowed exception. → `references/config.md`
- ❌ `os.getenv()` scattered across modules — all env var access must go through the `Settings` singleton.
- ❌ Internal types in public APIs — use TypedDicts / DTOs.
- ❌ **Using a Lambda `event` dict or ECS env block raw** — parse it into a Pydantic model at the boundary first. → `references/data-modeling.md`
- ❌ **Hard-coded test ids / shared test data / cross-tenant FK in seeds** — dynamic ids, per-test ownership, FKs stay within one tenant. → `references/testing.md`
- ❌ **A global (all-tenant) job that can't run for a single customer** — add an optional scope param; make DDB idempotency scope-aware so a global run supersedes a customer run. → `references/scoped-processes.md`
- ❌ Mixed I/O + business logic in one function.
- ❌ `except Exception: pass` — catch specific, log context, re-raise as needed.
- ❌ **`contextlib.suppress(Exception)` — strictly prohibited.** Silences all exceptions including bugs, OOM, and `KeyboardInterrupt`. `suppress(SpecificError)` is allowed only with an inline comment explaining why swallowing that specific error is intentional and safe.
- ❌ Ignoring partial failures in batch ops — return successes + failures.
- ❌ Skipping input validation at API/function boundaries.
- ❌ Blocking calls in async — use `run_in_thread()` (see `references/async-patterns.md`).
- ❌ Untyped collections (`list`, `dict` no params).

## Quick review checklist

Before finalising code:

- [ ] All functions: type hints (params + return)
- [ ] All functions: Google-style docstrings
- [ ] No scattered timeout / retry logic
- [ ] No mixed I/O + business logic
- [ ] No bare `except Exception: pass`
- [ ] No `contextlib.suppress(Exception)` — use narrow `suppress(SpecificError)` with justification comment only
- [ ] Batch ops handle partial failures
- [ ] Collections have type parameters
- [ ] Resources use context managers or explicit cleanup
- [ ] No double retry (app + infrastructure)
- [ ] No hardcoded config at module/class level (model names, statuses, resource names, endpoints, timeouts → Settings)
- [ ] No exposed internal types in APIs
- [ ] Input validated at boundaries
- [ ] Lambda events / ECS env vars parsed into a Pydantic model at the entry point
- [ ] Tests: dynamic DB ids, per-test data ownership, no cross-tenant FK, green under `-n auto`
- [ ] Global jobs accept a scope param; DDB idempotency includes scope (global run supersedes customer run)
- [ ] Thread-safe
- [ ] No blocking calls in async
- [ ] `raise` specific (`ValueError`, `TypeError`), not generic `Exception`
- [ ] All async functions awaited
- [ ] Lambda handlers: `lambda_handler` is sync one-liner (`uvloop.run(main(event))`), all logic in `async def main()`
- [ ] Tests cover error paths + edge cases

## Pre-commit checklist

Before committing:

- [ ] README updated
- [ ] CHANGELOG updated
- [ ] All tests green (incl. pyleak loop + thread leak checks)
- [ ] prek (pre-commit) clean
- [ ] mypy clean
- [ ] ruff clean (lint + format)

## When in doubt

Pull the relevant reference file via the table above. The references hold the full examples (200-700 lines each); the SKILL.md keeps the rules + entry points.
