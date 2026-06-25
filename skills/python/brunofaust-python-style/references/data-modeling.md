# Data Modeling — TypedDict vs Dataclass vs Pydantic

**Decision rule:** Pydantic at trust boundaries, frozen dataclasses for internal contracts, TypedDict only for static test data.

## Trust boundaries — use Pydantic `BaseModel`

- External API responses parsed into our domain
- FastAPI request/response schemas
- DynamoDB read payloads
- Hook configs from user-controlled sources
- Configuration loaded from files or env (use `pydantic-settings`)
- **Lambda event payloads** — SQS / SNS / EventBridge records, Step Functions
  state input, direct-invoke JSON. The `event: dict[str, Any]` AWS hands you is
  untrusted shape; parse it into a model as the first line of `main()`.
- **ECS task inputs** — container env vars (via `pydantic-settings`) and any JSON
  passed through a command override / `containerOverrides`. Same rule: validate
  before use.

**Every entry point parses its payload.** A Lambda `event`, an ECS env block, an
SQS message body, a Step Functions input — none of them are trusted dicts. The
boundary parse is mandatory, not optional, and it is the place that catches a
malformed deploy or a renamed field *loudly* instead of as a `KeyError` three
calls deep.

## Lambda event + ECS env — the boundary parse

```python
import uvloop
from typing import Any
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings


class RollupEvent(BaseModel):
    """Validated Lambda event — the untyped `event` dict is parsed here, once."""

    model_config = {"extra": "forbid", "frozen": True}

    run_date: str
    customer_ids: tuple[str, ...] = Field(default_factory=tuple)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS entry point — sync shell, async body."""
    return uvloop.run(main(event))


async def main(event: dict[str, Any]) -> dict[str, Any]:
    """Parse the untrusted event at the boundary, then run typed logic."""
    parsed = RollupEvent.model_validate(event)  # raises ValidationError on bad shape
    return await run_rollup(parsed)
```

ECS containers read their inputs from env vars — validate them through a
`pydantic-settings` model at startup so a missing or malformed var crashes the
task immediately with a clear message (fail-fast), never mid-run:

```python
class TaskSettings(BaseSettings):
    """ECS task inputs — env vars validated at container startup."""

    run_date: str = Field(alias="RUN_DATE")
    customer_ids: tuple[str, ...] = Field(default_factory=tuple, alias="CUSTOMER_IDS")

    model_config = {"extra": "ignore"}


TASK_SETTINGS = TaskSettings()  # fails fast at import if RUN_DATE is unset
```

`model_config = {"extra": "forbid"}` on event models surfaces a renamed or stray
field as a `ValidationError` at the boundary instead of silently ignoring it. See
[`config.md`](config.md) for the full `pydantic-settings` patterns (coercion,
secrets, nested groups) and [`scoped-processes.md`](scoped-processes.md) for the
scope parameter that rides on these payloads.

## Internal contracts — use `@dataclass(frozen=True, slots=True)`

- Data passed between modules within our system
- Return types of business-logic functions
- Domain models in `domain/models/`
- Already-validated data flowing between features

## Static test fixtures — TypedDict acceptable

- `tests/conftest.py` fixture types
- Function-internal dicts that never cross module boundaries

## Anti-pattern — `dict[str, Any]` between functions

```python
# BAD: dict[str, Any] passed between functions
def process_ticket(task: dict[str, Any]) -> dict[str, Any]:
    summary = task.get("summary", "")
    comments = task.get("comments", []) or []
    for c in comments:
        body = c.get("body") or ""
        ...
```

## Correct — boundary parsing with Pydantic

```python
from pydantic import BaseModel, Field, field_validator


class Comment(BaseModel):
    body: str = ""
    author: str | None = None


class Ticket(BaseModel):
    model_config = {"validate_assignment": True, "extra": "ignore"}

    ticket_key: str
    summary: str = ""
    description: str | None = None
    labels: list[str] = Field(default_factory=list)
    comments: list[Comment] = Field(default_factory=list)

    @field_validator("labels", "comments", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        return v or []
```

## Correct — internal contract with frozen dataclass

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TicketContext:
    """Context assembled for a ticket. Already validated upstream."""

    ticket_key: str
    parent_summary: str | None
    siblings: tuple[str, ...]
    subtasks: tuple[str, ...]
```

## Performance note

Pydantic validation costs ~1-5μs per simple model. Don't re-validate trusted data. Use `model_construct()` to bypass validation when reading from a trusted source.

## Don't

- Pydantic for SQLAlchemy row dicts (DB schema already enforces). Use SQLAlchemy models or keep dicts.
- Pydantic for truly arbitrary blobs (`metadata: dict[str, Any]` passthroughs).
- Pydantic inside hot loops over already-validated data.

## Enforcement

- mypy strict — catches `dict[str, Any]` leakage at function signatures.
- `skill_enforcer.py` rule `no_dict_any_in_signatures` (see `references/enforcement.md`).
