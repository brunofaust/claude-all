# Project Structure

Template layout for all Python projects. Enforce dependency direction via `import-linter`; mirror src/ in tests/.

## Top-level layout

```
src/<project>/
├── __init__.py                      # __all__ exports public API
├── __main__.py                      # CLI entry
├── settings.py                      # pydantic-settings singleton — lives at ROOT, never in core/
│
├── domain/                          # ← BUSINESS LOGIC, pure Python, no I/O
│   ├── models/                      # Pydantic boundary models + frozen dataclasses
│   ├── errors.py                    # domain exceptions
│   └── protocols.py                 # Protocol definitions for DI
│
├── features/                        # ← FEATURE MODULES (vertical slices)
│   └── <feature_name>/
│       ├── service.py               # business logic
│       ├── pipeline.py              # orchestration
│       ├── models.py                # feature-internal dataclasses
│       └── README.md
│
├── integrations/                    # ← EXTERNAL SYSTEM OWNERS
│   └── <system>/                    # one folder per external system
│       ├── client.py                # THE single owner — all HTTP/SDK here
│       ├── parser.py                # response parsing
│       ├── models.py                # raw response shapes
│       └── __init__.py              # __all__ = ["<System>Client"]
│
├── aws_resources/                   # ← AWS RESOURCES BY TYPE & NAME
│   ├── README.md                    # index of all resources
│   ├── CLAUDE.md                    # orchestration map
│   │
│   ├── lambdas/
│   │   ├── README.md
│   │   ├── CLAUDE.md
│   │   ├── <lambda_name>/
│   │   │   ├── handler.py           # entry point (thin glue only)
│   │   │   ├── Dockerfile
│   │   │   ├── README.md            # human-facing
│   │   │   └── CLAUDE.md            # AI-facing
│   │   └── _shared/                 # shared lambda utils
│   │
│   ├── ecs_tasks/<task_name>/
│   │   ├── entrypoint.sh
│   │   ├── runner.py
│   │   ├── Dockerfile
│   │   ├── README.md
│   │   └── CLAUDE.md
│   │
│   ├── batch_jobs/<job_name>/
│   ├── step_functions/<sfn_name>/
│   │   └── asl.json.tftpl
│   ├── codebuild_projects/<project>/
│   │   └── buildspec.yml
│   └── glue_jobs/<job_name>/
│
├── api/                             # ← FastAPI (thin, no business logic)
│   ├── app.py
│   ├── dependencies.py
│   ├── permissions.py
│   ├── exceptions.py
│   ├── middleware.py
│   ├── auth/
│   ├── routes/                      # one file per resource
│   ├── schemas/                     # Pydantic request/response (split per resource)
│   └── graphql/                     # ← OPTIONAL GraphQL layer
│       ├── schema.py
│       ├── types/
│       ├── queries/
│       ├── mutations/
│       ├── subscriptions/
│       ├── resolvers/
│       ├── loaders/                 # DataLoader instances
│       ├── permissions.py
│       └── context.py
│
├── db/                              # ← PERSISTENCE
│   ├── models.py                    # SQLAlchemy ORM
│   ├── connection.py
│   ├── repositories/                # one file per resource (replace monolithic crud.py)
│   └── queries/                     # named SQL constants
│
├── cli/                             # CLI commands
├── core/                            # ← SETTINGS-FREE, REUSABLE BUILDING BLOCKS
│   │                                #   Zero imports from settings/ or any project-specific module.
│   │                                #   Designed to be liftable into a standalone shared library.
│   ├── logging.py                   # structlog setup (takes config as args — never imports settings)
│   ├── telemetry.py
│   ├── cache.py
│   ├── retry.py
│   ├── time.py
│   ├── thread_pool.py               # run_in_thread() for wrapping sync SDK calls
│   ├── aws/                         # AWS SDK owners — one file per service (the boto3/aiobotocore owner)
│   │   ├── base.py                  #   shared AWSClient + process-wide aiobotocore session reuse
│   │   ├── s3.py  ├ sqs.py  ├ sns.py  ├ dynamodb.py  ├ secrets.py  └ … (one per service)
│   ├── ai/                          # AI provider clients (settings-free; model id passed in)
│   └── <integration_family>/        # generic connector abstractions (Protocol + factory + concretes)
└── utils/                           # truly generic stateless helpers only (no I/O, no SDK)

tests/
├── unit/                            # mirror src/
├── integration/
├── e2e/
├── conftest.py
├── factories/
└── fixtures/

docs/
├── architecture/
│   ├── decisions/                   # ADR-NNN files
│   └── diagrams/
├── runbooks/
├── PRDs/
└── user-guide/

infra/                               # Terraform
scripts/                             # dev/ops scripts
```

## Dependency direction (strict)

```
entry_points (api, lambdas, cli) → features → integrations / aws_resources / db
                                  → settings ← (everyone reads settings; settings reads nothing)
                                  → domain ← (everyone reads domain; domain reads nothing)
                                  → core ← (everyone reads core; CORE READS NOTHING PROJECT-SPECIFIC)
```

## `core/` is a settings-free, extractable library

This is the single most important rule about `core/`: **it imports nothing
project-specific — not `settings`, not `domain`, not `features`.** Everything in
`core/` is a self-contained building block (an AWS client wrapper, a retry
decorator, a thread-pool helper, a connector Protocol) that you could lift into a
standalone PyPI package shared across services without changing a line.

- Configuration is **injected** (passed as constructor args / function params),
  never imported. That's why `settings.py` lives at the package root, NOT in
  `core/` — putting settings in core would couple it to this project and break
  extractability.
- SDK ownership lives here, contained per service: `core/aws/<service>.py` (the
  boto3/aiobotocore owner) with a shared `core/aws/base.py`. See
  `external-system-ownership.md`.
- Test for violations: `core/` must pass
  `lint-imports` with a contract that forbids `core` → `settings`/`domain`/`features`.

## Three folder types — never mix

- **Vertical (feature):** `features/<name>/` — owns its service, models, internal helpers
- **Horizontal (integration):** `integrations/<system>/` — owns one external system
- **Infrastructure:** `db/`, `aws_resources/` (deployable units) — project-coupled, cross-cutting
- **Settings-free building blocks:** `core/` — reusable, project-agnostic, extractable as a library

## Where the seams are — one module, one secret

**Domain tells you which FOLDER. It does not tell you where the seams are.** Grouping by domain is
necessary and not sufficient: "AI models" is one domain, so a rule that says *"one file per domain,
the single home for everything about it"* actively instructs you to pile orchestration, billing
policy, vendor routing and request shapes into one file — and then a 1,300-line module is the rule
working as designed. That rule is wrong at the file level. The correct axis is **reason to change**,
subordinate to **dependency ownership**.

### The rule

> **A module hides ONE SECRET** — one design decision that can change independently.

Billing-account policy is a secret. A vendor SDK's invoke-vs-converse footgun is a secret. A vendor's
request shape is a secret. How you orchestrate a call is a secret. Each changes for its own reason, on
its own clock, often with a different owner — so each is its own module.

### The operational tests

1. **Split when two chunks change for different reasons, at different rates, or have different
   owners.** The sharp form: *would these ever appear in the same PR, for the same reason?* If no,
   they are separate secrets — split them.
2. **Keep together when they always change together** — same PR, same reason. **Fat is fine if the
   whole file has one reason to change.**
3. **Place by dependency ownership.** Code lives in the module that owns the dependency it touches.
   Anything whose only real dependency is a vendor SDK belongs in that vendor's owner module, full
   stop — that is why vendor request-shape helpers feel wrong sitting in a coordinator. (This is the
   containment rule of `external-system-ownership.md`, stated precisely.)
4. **False-seam test.** If splitting would force you to expose internals across the new boundary —
   shared mutable state, private helpers that must now be imported — the cohesion is **real**. Don't
   split. This is what stops the rule degenerating into the linter's "just split it".
5. **LOC is a smell, never a criterion.** Never split to hit a line target; never merge to hit one
   either. A long file is a prompt to *ask* the questions above, not an answer.

**A coordinator / facade is allowed to be large.** Its one reason to change is "how we orchestrate a
call". It is too big only when it **smuggles in a different secret** — a billing table, a vendor's
payload shape, a retry policy that belongs to the transport.

### Worked example — a 1,300-line model coordinator

```text
core/ai/model.py   (1,300 lines)  ← FOUR secrets in one file
    class Model, ModelConfig                     ← orchestration   (secret 1)
    resolve_caller_account, resolve_credential   ← billing policy  (secret 2)
    resolve_bedrock_invocation, TruncatedError   ← Bedrock routing (secret 3)
    resolve_endpoint_template                    ← vendor shape    (secret 4)
```

Applying the tests: billing policy changes when Finance changes plans; the Bedrock routing rule changes
when that SDK changes; the endpoint template changes when the vendor changes its API. None of those
share a PR or a reason with "how we orchestrate a call". Split:

```text
core/ai/model.py       orchestration only — may stay large, it has ONE reason to change
core/ai/billing.py     account/credential policy
core/aws/bedrock.py    invoke-vs-converse routing  ← dependency ownership: its only dep is the SDK
core/ai/vendors/<v>.py the vendor's request shape
```

### Grouping still applies — it just answers a different question

Domain grouping prevents **scatter**: a namespace root that accretes 20+ loose modules because every
change dropped a new file next to the last one (`working_hours.py`, `re_engage.py`, `branch_naming.py`,
…). The raw file *count* is rarely the problem — a broad product legitimately has many files — the
problem is *no grouping principle*, plus incomplete refactors (a 900-line monolith beside a package
that re-imports it) and name-collisions (`email/` next to `emails/`).

- **A file (or folder) maps to a domain concept — never to a business _requirement_** (a feature,
  ticket, or behaviour). New behaviour joins an existing home; it does not get a new top-level file.
  Domain answers *"which folder?"*; reason-to-change answers *"which file inside it?"*.
- **Promote a domain to a _package_** (a directory with a single public `__init__.py` entrypoint) when
  it holds several secrets or has real variant seams — pluggable collectors/providers
  (`abuse/collectors/{jira,github}.py`, `ai/llm/{openai,anthropic}.py`). Decide on the **real,
  post-deduplication** shape, never preemptively, and never a speculative `base.py` with one
  implementer. This is *containment over layering* (→ the `architecture-decision-guard` skill).
- **Cross-cutting single-owner modules** (`secrets.py`, `config.py`) may live at the namespace root —
  they are not domains, they are shared utilities with exactly one owner.

## Mechanism vs policy — domain code is glue

`core/<app>/<domain>/` holds business **policy** (the *what / when* — which secret, which ticket, what
rule), expressed as **glue** that composes generic `core/` **mechanisms** (the *how* — talk to SSM,
read a file, call an API, run a thread). This mirrors the outer layering: entry-point handlers are thin
glue over the domain, which is thin glue over generic `core/` primitives.

- **Mechanism → a generic single-owner:** `core/aws/<service>`, `core/<integration_family>/`,
  `core/thread_pool`, `core/subprocess`. Domain-agnostic, extractable (see
  `external-system-ownership.md`).
- **Policy → `core/<app>/<domain>`:** composes those mechanisms into a business flow.
- **Promote a mechanism to a generic owner on the _third_ copy** (the rule of three — see
  `architecture.md`), never preemptively. A "generic" module with one or two consumers is a speculative
  boundary — the exact smell to avoid. Note some things are *already* generic (async file I/O via
  `anyio.Path`; the thread-offload seam) — use the existing primitive, don't wrap it for one caller.

## Keep the namespace flat — enforce it, don't just document it

A rule in prose gets violated; a rule encoded as a checker holds. Enforce "one home per domain" with:

- **A root-allowlist gate** on the busy namespace (e.g. `core/<app>/` top level): seed it with today's
  legitimate modules; a *new* top-level file fails CI unless added to the allowlist with a one-line
  justification. This mechanically stops "every change → new root file".
- **Single-owner `banned-api` contracts** (mechanism containment) + the `import-linter` layer contracts
  below.
- **A semantic-duplication gate kept at a HIGH similarity threshold (~0.92).** Counter-intuitive but
  measured: *lowering* a semantic-duplication gate to "surface more reuse" is counterproductive — the
  low-similarity band is dominated by noise (matching control-flow ≠ shared intent), and real reuse
  candidates cluster at the *high* end. In one real codebase a `core/`-scoped scan returned ~133 pairs
  at 0.92, ~68k at 0.70, and ~420k at 0.50 (~82% pure noise). The lever for reducing files is
  domain-grouping + finishing refactors, **not** turning the duplication knob down.

## Entry points are thin

No business logic. Lambda handlers max 20 statements.

## Per-resource mandatory files

For `aws_resources/lambdas/<name>/`, `aws_resources/ecs_tasks/<name>/`, etc.:

- `handler.py` (or `entrypoint.sh` / `runner.py`)
- `Dockerfile` (for container-based resources)
- `README.md` (human-facing)
- `CLAUDE.md` (AI-facing)

## CLAUDE.md template per resource

```markdown
# <resource_name> — CLAUDE.md

## What it is
One-line description.

## Trigger
- Source: <SQS queue / EventBridge / etc>
- Event format: see _shared/event_parser.py

## Calls
- <feature service path>
- <other aws resources>

## Owns
- Dockerfile in this folder
- IAM policy at <terraform path>
- Env vars: <list>

## Common failures
- <symptom>: <fix>

## Local test
make test-lambda LAMBDA=<name>

## Related resources
- Upstream: <resource>
- Downstream: <resource>

## Logs
- CloudWatch: /aws/lambda/<name>
- Search: <correlation_id>=<value>
```

## Tests mirror src/ — ONE flat folder

`tests/unit/` is flat: one file per source module, named `test_<source path with '/' -> '_'>.py`.
No subdirectories, no non-mirror files (only `conftest.py` / `__init__.py`), no parallel
`*_extra` / `*_coverage[N]` grab-bags. See `testing.md`; enforced by `checkers/flat_test_mirror.py`.

```
src/<project>/core/aws/s3.py                     ->  tests/unit/test_core_aws_s3.py
src/<project>/features/pii_detection/service.py  ->  tests/unit/test_features_pii_detection_service.py
```

## `__init__.py` declares public API

```python
# integrations/jira/__init__.py
from .client import JiraClient

__all__ = ["JiraClient"]
```

An `__init__.py` holds **only a docstring and re-exports** — never implementation
logic (enforced by `RUF067`). Put code in a real module and re-export it here.
(This is the one legitimate "module that only imports"; a non-`__init__` module
left as a pure re-export is a shim — move it instead, see `architecture.md`.)

## Enforcement — `import-linter` contracts

```toml
[tool.importlinter]
root_packages = ["<project>"]

[[tool.importlinter.contracts]]
name = "Layered architecture"
type = "layers"
layers = [
    "<project>.api | <project>.cli | <project>.aws_resources",
    "<project>.features",
    "<project>.integrations | <project>.db",
    "<project>.domain | <project>.core",
]

[[tool.importlinter.contracts]]
name = "Domain has no dependencies on infra"
type = "forbidden"
source_modules = ["<project>.domain"]
forbidden_modules = [
    "<project>.api", "<project>.features", "<project>.integrations",
    "<project>.db", "<project>.aws_resources",
]

[[tool.importlinter.contracts]]
name = "core is a settings-free extractable library"
type = "forbidden"
source_modules = ["<project>.core"]
forbidden_modules = [
    "<project>.settings", "<project>.domain", "<project>.features",
    "<project>.integrations", "<project>.db", "<project>.aws_resources", "<project>.api",
]
```
