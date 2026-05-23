______________________________________________________________________

## name: brunofaust-python-style description: > Modern Python 3.14+ coding standards for async-first, type-safe production code. Use when: writing async Python code, building CDC pipelines, implementing data transformations, adding type hints, setting up pytest fixtures, designing dataclasses, reviewing code for Python best practices, optimizing async patterns, or creating data engineering features. Enforce for all Python coding tasks: new features, refactoring, bug fixes, type safety reviews, async/await patterns, structured logging, datalake silver/gold layer transformations. disable-model-invocation: false user-invocable: true

# Python Coding Style Guide (condensed)

Production-grade async Python. Async-first, strict types, immutable parameter types, 100% docstrings, real-infra tests (LocalStack).

**This is the condensed entry point.** Depth and full examples live under `references/`. Read the relevant reference file before deep work in that area.

## Core principles

1. **Python 3.14+** — pipe unions (`str | None`), `match` statements, `asyncio.TaskGroup`, `exception.add_note()`.
1. **Async everything** — custom functions are `async def`. Exceptions: `__init__`, `__iter__`, `__enter__`, other stdlib sync dunder methods.
1. **Immutable parameter types** — `Mapping`/`Sequence` from `collections.abc`, not `dict`/`list`. Required for cached function inputs/outputs.
1. **Type safety first** — full type hints, `TypedDict`, `Literal`, `@overload`. Enforced via mypy (strict) + Ruff.
1. **100% docstring coverage** — Google-style with Args / Returns / Raises / Examples.
1. **Test everything** — `MonkeyPatch.context()` for mocks. Unit + integration (LocalStack) + class structural tests. Data tests cover the full data lifecycle.

## Table of references

Read the matching file BEFORE deep work in that area. Each is a focused reference, not a full re-implementation of the rules.

| If you are…                                                                                                                                                                                    | Read                                                                                 |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Writing docstrings, public APIs, package docs                                                                                                                                                  | [`references/docstrings.md`](references/docstrings.md)                               |
| Adding generics, Protocols, type aliases, TYPE_CHECKING decisions                                                                                                                              | [`references/type-hints.md`](references/type-hints.md)                               |
| Touching `try/except`, designing exception hierarchies, using `suppress()`, handling AWS / boto errors                                                                                         | [`references/error-handling.md`](references/error-handling.md)                       |
| Designing classes — inheritance for service wrappers, DI, class attributes                                                                                                                     | [`references/class-design.md`](references/class-design.md)                           |
| Implementing caching, TTL caches, cache invalidation                                                                                                                                           | [`references/caching.md`](references/caching.md)                                     |
| Setting up `pyproject.toml`, project bootstrap, ruff/mypy config                                                                                                                               | [`references/pyproject-toml.md`](references/pyproject-toml.md)                       |
| Bootstrapping a new project                                                                                                                                                                    | [`references/installation.md`](references/installation.md)                           |
| Writing README, CHANGELOG, project docs                                                                                                                                                        | [`references/project-docs.md`](references/project-docs.md)                           |
| Architectural decisions — KISS, SRP, Separation of Concerns, Composition>Inheritance, Rule of Three, function size, DI, anti-patterns                                                          | [`references/architecture.md`](references/architecture.md)                           |
| Writing/optimizing async code — TaskGroup, ExceptionGroup, `run_in_thread`, semaphores, rollback, FIFO, pagination                                                                             | [`references/async-patterns.md`](references/async-patterns.md)                       |
| Configuration management — Pydantic Settings, env var coercion, nested configs, secrets from files                                                                                             | [`references/config.md`](references/config.md)                                       |
| Writing tests — pytest, fixtures, parametrize, mocks, LocalStack, time freezing, snapshot, **factory pattern (polyfactory/factory_boy), DI over module-global mocks, mirrored src/ structure** | [`references/testing.md`](references/testing.md)                                     |
| Choosing between Pydantic / dataclass / TypedDict — trust boundaries, internal contracts, test fixtures                                                                                        | [`references/data-modeling.md`](references/data-modeling.md)                         |
| Owner-class pattern for external systems (Jira, AWS, OpenAI…), ruff `banned-api` config, audit recipe                                                                                          | [`references/external-system-ownership.md`](references/external-system-ownership.md) |
| Module-level visibility — `__all__` over `_` prefix, vulture/ruff blind-spot fix                                                                                                               | [`references/visibility.md`](references/visibility.md)                               |
| Debugging AWS dev environments — full-run → isolate → hotfix vs deploy → parallel pieces → SF splitting → verify                                                                               | [`aws-debug-loop` skill](../../aws/aws-debug-loop/SKILL.md)                          |
| Project folder layout — `domain/features/integrations/aws_resources/api/db`, per-resource files, `import-linter` contracts                                                                     | [`references/project-structure.md`](references/project-structure.md)                 |
| Enforcement matrix — every rule → ruff code / `skill_enforcer.py` rule / prek hook / GH Action                                                                                                 | [`references/enforcement.md`](references/enforcement.md)                             |

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
import orjson
import polars as pl
from cachetools import TTLCache

# 3. Local
from app import CACHE_1_HOURS
from app.core.cache import cached_async
```

Rules: parenthesised imports for large groups, `TYPE_CHECKING` for type-only imports, **never** wildcard imports, **never** `from __future__ import annotations` (deprecated in 3.14 per PEP 649).

Full TYPE_CHECKING semantics + Protocol typing + generics → `references/type-hints.md`.

## Modern Python idioms (3.14+)

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

Multi-exception in one except (PEP 758, 3.14+): `except ValueError, TypeError:` — no parens needed. See `references/error-handling.md`.

## Preferred libraries

| Purpose              | Use             | Never                         |
| -------------------- | --------------- | ----------------------------- |
| DataFrames           | **Polars**      | pandas                        |
| JSON                 | **orjson**      | stdlib `json`                 |
| Event loop           | **uvloop**      | default asyncio loop          |
| Hashing (non-crypto) | **xxhash**      | hashlib                       |
| AWS SDK              | **aiobotocore** | sync `boto3` in async code    |
| Caching              | **cachetools**  | `functools.lru_cache`         |
| Logging              | **structlog**   | stdlib logging with f-strings |
| Dependencies         | **uv**          | pip                           |

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

1. **Data modeling.** Pydantic at trust boundaries, frozen dataclasses internally, TypedDict only for static test data. Never pass `dict[str, Any]` between modules. → `references/data-modeling.md`
1. **External system ownership.** One owner class per external system (Jira, S3, OpenAI, …). All SDK / HTTP calls flow through it; ruff `banned-api` blocks raw imports outside owner folders. → `references/external-system-ownership.md`
1. **Error handling discipline.** No silent except. No `log.debug` inside `except`. Catch narrowest class, log at `warning`/`error` with structured context, `raise ... from e` when converting. → `references/error-handling.md`
1. **Test patterns.** Use factories (polyfactory / factory_boy). Never `mod._client = mock` (race-prone under xdist) — inject the dependency. Tests mirror `src/` 1:1. → `references/testing.md`
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
- ❌ Wildcard imports.
- ❌ Global mutable state → pass context objects.
- ❌ `from __future__ import annotations` — deprecated post-PEP 649.
- ❌ Committing secrets / API keys.

### Architecture

- ❌ Scattered retry / timeout logic — centralise in decorators / client wrappers.
- ❌ Retry at multiple layers (app + client lib) — pick ONE.
- ❌ **Hardcoded config at module or class level** — any value that could differ between environments or change over time must live in `Settings`, env var, or be passed as a parameter. Covers: LLM model names, Jira/workflow statuses, S3/SQS/SNS resource names, API endpoints, timeouts, batch sizes, feature flags. Function/method *parameter defaults* are the one allowed exception. → `references/config.md`
- ❌ `os.getenv()` scattered across modules — all env var access must go through the `Settings` singleton.
- ❌ Internal types in public APIs — use TypedDicts / DTOs.
- ❌ Mixed I/O + business logic in one function.
- ❌ `except Exception: pass` — catch specific, log context, re-raise as needed.
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
- [ ] No bare `except Exception: pass` (unless intentional)
- [ ] Batch ops handle partial failures
- [ ] Collections have type parameters
- [ ] Resources use context managers or explicit cleanup
- [ ] No double retry (app + infrastructure)
- [ ] No hardcoded config at module/class level (model names, statuses, resource names, endpoints, timeouts → Settings)
- [ ] No exposed internal types in APIs
- [ ] Input validated at boundaries
- [ ] Thread-safe
- [ ] No blocking calls in async
- [ ] `raise` specific (`ValueError`, `TypeError`), not generic `Exception`
- [ ] All async functions awaited
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
