# Data Modeling — TypedDict vs Dataclass vs Pydantic

**Decision rule:** Pydantic at trust boundaries, frozen dataclasses for internal contracts, TypedDict only for static test data.

## Trust boundaries — use Pydantic `BaseModel`

- External API responses parsed into our domain
- FastAPI request/response schemas
- DynamoDB read payloads
- Hook configs from user-controlled sources
- Configuration loaded from files or env (use `pydantic-settings`)

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
