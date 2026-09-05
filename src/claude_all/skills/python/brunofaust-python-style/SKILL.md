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
`model_contract.py`, `lambda_event_validation.py`, `flat_test_mirror.py`,
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
| Writing/optimizing async code — TaskGroup, ExceptionGroup, `run_in_thread`, semaphores, rollback, FIFO, pagination                                                                             | [`references/async-patterns.md`](references/async-patterns.md)                                          |
| Understanding and using Python 3.14 free-threaded execution — when to use, implementation patterns, and dependency compatibility                                                             | [`references/free-thread-python-3.14.md`](references/free-thread-python-3.14.md)                      |
| Writing AWS Lambda handlers — async entry point with `uvloop.run()`, `main()` pattern                                                                                                          | See `## Lambda handlers` section below + [`references/async-patterns.md`](references/async-patterns.md) |
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

Rules: parenthesised imports for large groups, `TYPE_CHECKING` for type-only imports, **never** wildcard imports, **never** `from __future__ import annotations` on the 3.14+ baseline — PEP 649 already makes annotations lazy by default, so the import is dead weight. **Never alias an import to a `_`-prefixed name** (e.g. `import orjson as _orjson`) — module-level names never start with `_` (that's what `__all__` is for, see Visibility rule), and an alias must *mean something* (disambiguation, convention like `import polars as pl`), not act as a visibility hack. If you're aliasing to hide a name, you want `__all__` instead.

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

Multiple exceptions in one except: PEP 758's paren-less form `except ValueError, TypeError:` is available on the 3.14 baseline; the parenthesised tuple `except (ValueError, TypeError):` stays valid. See `references/error-handling.md`.

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

1. **Minimalism / YAGNI — the default.** Simplest thing that satisfies the CURRENT requirement; structure is a cost, not a virtue. Name a concrete *present* reason for every function, class, file, and abstraction — "might need it later", "more flexible", "cleaner", "best practice", "separation of concerns" are not reasons. Target shapes: one table = one class + its Pydantic model (`get_x(id)` returns the model, nothing else); called once → inline it; one implementation → no interface/`Protocol`; one method → no class. Banned by default: pass-through functions, a "repository" wrapping SQLAlchemy, factories/strategies/registries/managers/single-subclass bases, config for one-value options, defensive handling of type-guaranteed inputs. Abstract at the **third** real case (Rule of Three), a real second impl *today*, or a genuine test seam — never on speculation. (Rule of Three governs *uncertain* similarity; **structurally-certain** sameness — a second call site on the same store surface, or a second copy of the same control-flow skeleton — extracts at the **second** copy, → `references/architecture.md` "Rule of Three vs the two-copy trigger".) Run a **deletion pass** before finishing: for each unit, name the present need or inline/remove; bias toward deleting; fewer, longer, obvious functions beat many tiny indirections. Exception: foundations that are expensive to reverse (boundary models, schema/DB, security/tenant boundaries, module layout) warrant foresight now — YAGNI governs features, not foundations. The heavier patterns in `architecture.md` are tools for a justified need, not defaults. → `references/yagni.md`
1. **Data modeling.** Default to a **Pydantic model everywhere a contract exists** — at trust boundaries AND internally; a `@dataclass` is the rare allowlisted exception (only for a proven structural reason: holds a live non-serializable object, is a DI container, carries a `TYPE_CHECKING`-only type, or is a `dataclasses.replace()` target — never "it's already validated"). For a hot loop over trusted data use `model_construct()` on a real model, not a dataclass. Models start from one shared `PYDANTIC_CONFIG`; verbatim-content fields opt out of `str_strip_whitespace`. **`TypedDict` is banned outright** (static-only — it validates nothing at runtime, including in test fixtures) and **`typing.cast` is banned** (`cast(row_dtype, dict(row))` proves nothing — use `Model.model_validate(...)`). **`extra="forbid"` on every model, no exceptions** (consumer-before-producer is a deployment-order problem to solve in the deploy process, never a reason to weaken the contract). No default on a required field; no `Any`/bare `dict` as a model field; never pass `dict[str, Any]` between modules. **Every entry point validates its payload** — Lambda events (SQS/SNS/EventBridge/Step Functions/direct invoke) and ECS env vars (`pydantic-settings`) are parsed into a Pydantic model at the boundary, before any logic. → `references/data-modeling.md`
1. **External system ownership — including query surfaces.** One owner class per external system (Jira, S3, OpenAI, …); all SDK / HTTP calls flow through it; ruff `banned-api` blocks raw imports outside owner folders. A **query surface** (a DB table, search index, vector namespace, cache keyspace) is an external system too — exactly ONE module owns its reads/writes; callers never assemble store access inline and build only inputs/outputs. **The trigger is the SECOND call site**, not the third (structurally-certain sameness, not Rule-of-Three doubt). **Structural duplication is invisible to clone detectors** (`jscpd` sees copy-paste, not same-responsibility-different-text — one real case hid ~1,700 LOC across three hand-assembled call sites): review by responsibility ("who else talks to this store/API?"), especially when a PR adds a new call site touching an existing store. → `references/external-system-ownership.md`
1. **Error handling discipline.** No silent except. No `log.debug` inside `except`. Catch narrowest class, log at `warning`/`error` with structured context, `raise ... from e` when converting. **`contextlib.suppress(Exception)` is strictly prohibited** — it silences all exceptions including bugs and OOM; `suppress(SpecificError)` requires explicit justification. → `references/error-handling.md`
1. **Test patterns.** Use factories (polyfactory / factory_boy). Never `mod._client = mock` (race-prone under xdist) — inject the dependency. Tests mirror `src/` 1:1. **Test data is isolated**: dynamic DB ids (never hard-coded), each test owns its own rows (nothing shared), FKs never cross tenants, suite runs under `pytest-xdist` (concurrency *is* the isolation check). **No `@pytest.mark.xdist_group`** to prop up co-dependent tests — make each test self-contained; the marker is a rare, user-approved, documented exception only. → `references/testing.md`
1. **Scoped global processes.** Every all-tenant job (Lambda/ECS) accepts an optional scope to run for one entity or a group — one code path (`scope or list_all()`), absent scope = global. DynamoDB idempotency includes the scope: a global run **supersedes** a customer-scoped run (the customer claim is blocked when a global run already covers it). Enables both e2e test isolation and single-customer production re-runs. → `references/scoped-processes.md`
1. **Multi-tenant isolation — the tenant id honored on every plane (two-layer, not optional).** App-side `WHERE org_id` is the first wall; a second wall on each plane makes a forgotten filter structurally impossible. The tenant id enters at **one** boundary — a typed context model parsed first thing, org from the auth token claim only (never a client param → IDOR), a provenance-typed `TenantScope` (not a bare `org_id`) carried to the data layer. Then it is honored across: **data** (Postgres RLS — a `STABLE app_current_org_id()` that RAISES on unset, `ENABLE`+`FORCE`, policy `USING (org_id = fn() OR fn() = 0)` with `0` a schema-reserved platform sentinel, `query_system(platform_scan=True)` per cross-org call site, a coverage-guard test); **process memory** (never a global cache on tenant-bound state — key the tenant id positional-only, build handlers per-invocation, clear log contextvars; warm workers leak, one-shot containers don't); **ephemeral disk** (`/tmp/{org_id}/{execution_id}/` via one path owner + cold-start orphan sweep since SIGKILL skips `finally`); **AWS resources** (ABAC via STS session tags conditioned on `${aws:PrincipalTag/org_id}` — spike support per service, org-keyed STS cache, FAIL-CLOSED on mint failure, a customer role with no ai-model perms so billing isolation is IAM not review). → `references/tenant-isolation.md`
1. **Visibility.** Module-level names never start with `_` — use `__all__`. Class-scope `self._x` is fine. The `_`-prefix blinds vulture, ruff, pyright to dead-code at module scope. → `references/visibility.md`
1. **Project structure — and module seams.** `domain/` (pure logic) → `features/` (vertical slices) → `integrations/` + `aws_resources/` + `db/` (horizontal). Entry points (`api/`, `cli/`, lambdas) stay thin. Enforce direction with `import-linter`. **Domain tells you which FOLDER; it does not tell you where the seams are** — inside it, **one module hides ONE SECRET** (one design decision that can change independently). Split when two chunks change for different reasons / rates / owners (*would they ever share a PR for the same reason?*); keep together when they always change together — **fat is fine if the whole file has one reason to change**. Place by **dependency ownership** (code whose only real dep is a vendor SDK lives in that vendor's owner module). If splitting would force exposing internals, the cohesion is real — don't split. **LOC is a smell, never a criterion**: a coordinator with one reason to change may legitimately be large; it's too big only when it smuggles in a different secret. → `references/project-structure.md`
1. **Documentation discipline.** Every code change ships with doc update. Mandatory files: README, CLAUDE.md (root + per resource), ARCHITECTURE, TODO. No CHANGELOG.md — it's a merge-conflict magnet across parallel PRs; release notes come from Conventional Commits history instead. Prek hooks + GH Actions block merge if docs stale. → `references/project-docs.md`
1. **No hardcoded config values.** Nothing that could change between environments, deployments, or over time may be hardcoded at module or class level. LLM model names, Jira/workflow statuses, S3/SQS/SNS resource names, API endpoints, timeouts, batch sizes, feature flags → all go in `Settings`. The only exception: *function/method parameter defaults* (they're explicit call-site overrides, not hidden globals). `os.getenv()` outside `Settings` is also banned. → `references/config.md`
1. **Enforcement.** Every rule maps to a checker — ruff code / vulture / `import-linter` / an AST checker under `checkers/` / prek hook / GH Action. No aspirational rules. The checkers ship as files but are **not** self-wiring: verify each is actually in the project's hook config on every invocation (see *Wiring the gates* above) — an unwired checker is prose. → `references/enforcement.md`

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
- ❌ **Using `from __future__ import annotations`** — PEP 649 makes annotations lazy by default on the 3.14+ baseline; the import is redundant dead weight.
- ❌ Committing secrets / API keys.

### Architecture

- ❌ Scattered retry / timeout logic — centralise in decorators / client wrappers.
- ❌ Retry at multiple layers (app + client lib) — pick ONE.
- ❌ **A second call site hand-assembling access to the same store surface** (DB table, search index, vector namespace, cache) — that store gets ONE owner module; callers build inputs/outputs only. Second copy is the trigger, not the third. → `references/external-system-ownership.md`
- ❌ **Trusting `jscpd`/clone gates to catch all duplication** — they see copy-paste, not same-responsibility-different-text. Review by responsibility ("who else talks to this store/API?") at every new call site on an existing store. → `references/external-system-ownership.md`
- ❌ **A second copy of the same control-flow skeleton** (cache-check→run→finish, fetch→build-result, guard→delete) — extract the skeleton as a higher-order helper at copy two; these families drift silently on one field. → `references/architecture.md`
- ❌ **A duplication-gate allowlist kept as a graveyard** — every entry is classified (`MERGE`/`EXTRACT-CORE`/`JUSTIFIED:<reason>`), entries naming deleted code are swept, and the list length only shrinks. → `references/enforcement.md`
- ❌ **Hardcoded config at module or class level** — any value that could differ between environments or change over time must live in `Settings`, env var, or be passed as a parameter. Covers: LLM model names, Jira/workflow statuses, S3/SQS/SNS resource names, API endpoints, timeouts, batch sizes, feature flags. Function/method *parameter defaults* are the one allowed exception. → `references/config.md`
- ❌ `os.getenv()` scattered across modules — all env var access must go through the `Settings` singleton.
- ❌ Internal types in public APIs — use Pydantic models / frozen-dataclass DTOs.
- ❌ **`TypedDict` — banned outright.** Static-only; it validates nothing at runtime. Test fixtures are where it lies most (a fixture that matches neither the DB nor the annotation keeps mypy green). Use a Pydantic `BaseModel`. → `references/data-modeling.md`
- ❌ **`typing.cast` — banned.** It asserts a type instead of proving one; `cast(row_dtype, dict(row))` is a no-op that only pretends to type. Use `Model.model_validate(...)`.
- ❌ **`extra="ignore"` / `extra="allow"` — always `extra="forbid"`.** A schema change must be followed by a code change. The consumer-before-producer deployment order this forces is a deploy-process problem, not a reason to weaken the contract.
- ❌ **A default on a field that is required** — that is the masking-default bug class (`.get(k, default)` is only its symptom). Model the payload; the required-vs-optional decision is then forced.
- ❌ **`Any` / bare `dict` / bare `Mapping` / `dict[str, Any]` as a model field** — the opaque VALUE is banned, never the container (`Mapping[str, str]` stays legal, and CORE PRINCIPLE #3 still stands). Genuinely polymorphic fields get documented, not a fabricated schema.
- ❌ **`f(**model.model_dump())` / `Model(**mapping)`** — name the fields. Logging (`log.bind(**ctx)`) is the ONLY exemption; SDK request-building is NOT.
- ❌ **`SELECT *`** — name the columns so the row's shape is one the code built end-to-end.
- ❌ **Credential / PII model fields without `Field(repr=False)`** — a model repr in a log line is a token leak. Verify empirically.
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
- [ ] No `TypedDict` anywhere (including fixtures); no `typing.cast` — `model_validate()` instead
- [ ] `extra="forbid"` on every model; queries name their columns (no `SELECT *`)
- [ ] No default on a required field; blanks normalised to `None` (unless `""` is persisted/forwarded)
- [ ] No `Any` / bare `dict` / opaque model fields; `Mapping[str, str]`-style typed values OK
- [ ] No `**` splatting except logging (`log.bind(**ctx)`)
- [ ] `Field(repr=False)` on credential / PII fields, verified with a real `repr()` assertion
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
- [ ] All tests green (incl. pyleak loop + thread leak checks)
- [ ] prek (pre-commit) clean
- [ ] mypy clean
- [ ] ruff clean (lint + format)

## When in doubt

Pull the relevant reference file via the table above. The references hold the full examples (200-700 lines each); the SKILL.md keeps the rules + entry points.
