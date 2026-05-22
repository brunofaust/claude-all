# Project Structure

Template layout for all Python projects. Enforce dependency direction via `import-linter`; mirror src/ in tests/.

## Top-level layout

```
src/<project>/
├── __init__.py                      # __all__ exports public API
├── __main__.py                      # CLI entry
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
├── core/                            # cross-cutting infrastructure
│   ├── config.py                    # pydantic-settings
│   ├── logging.py                   # structlog setup
│   ├── telemetry.py
│   ├── cache.py
│   ├── retry.py
│   └── time.py
└── utils/                           # truly generic helpers only

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
                                  → domain ← (everyone reads domain; domain reads nothing)
                                  → core ← (everyone reads core)
```

## Three folder types — never mix

- **Vertical (feature):** `features/<name>/` — owns its service, models, internal helpers
- **Horizontal (integration):** `integrations/<system>/` — owns one external system
- **Infrastructure:** `core/`, `db/`, `aws_resources/` — cross-cutting

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

## Tests mirror src/ exactly

```
src/<project>/features/pii_detection/service.py
tests/unit/features/pii_detection/test_service.py
```

## `__init__.py` declares public API

```python
# integrations/jira/__init__.py
from .client import JiraClient

__all__ = ["JiraClient"]
```

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
```
