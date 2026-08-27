# Data Modeling — Pydantic vs Dataclass (TypedDict is banned)

**Decision rule:** Pydantic everywhere a contract exists — at trust boundaries AND
for internal contracts. A `@dataclass` is the rare, allowlisted exception, used
only for a proven STRUCTURAL reason (see *Internal contracts* below), never as the
internal default: a dataclass validates nothing. **TypedDict is banned outright**
(checker rule `no-typeddict`), and so is `typing.cast` (checker rule `no-cast`).

## Gate findings: repair the contract

Fix the code; never weaken a contract or bypass a checker to clear a finding.

| Finding | Required repair |
| --- | --- |
| `extra-forbid` / unknown field | Update the consumer/schema together; keep `extra="forbid"`, never `ignore` or `allow`. |
| `masking-default` | Remove defaults from required fields. Optional fields use `T \| None = None` and explicit `None` handling. |
| `opaque-annotation` | Specify a concrete shape or value type; never widen to `Any`, remove annotations or add `type: ignore`. |
| `no-typeddict` / `no-cast` | Validate with `Model.model_validate(...)`. |
| `select-star` | Name query columns; do not loosen the model to absorb extras. |
| Parse failure / checker exit 2 | Pin the hook interpreter's `language_version`; never swallow `SyntaxError` or exclude unreadable code. |

Never hide a new finding with `--select`, `SKIP=`, `--no-verify`, `noqa`,
a suppression or a new baseline entry. Existing regression baselines do not authorize new debt.

## Why TypedDict is banned

**TypedDict is static-only — it validates NOTHING at runtime.** mypy checks the
annotation; the process never checks the data. Every masking-default bug in the
incident that produced this file lived under a TypedDict that mypy was happily
checking, reached through `cast(row_dtype, dict(row))` — a no-op that only
*pretends* to type.

Test fixtures are where TypedDict lies **most**, not least. A fixture read
`limits={"base_interval_seconds": 300}` and matched neither the database nor the
TypedDict. mypy stayed green. The fixture restated the code's assumptions instead
of reality.

```python
# BAD: static-only, runtime-blind — banned
class row_dtype(TypedDict):
    customer_id: str
    interval_seconds: int


row = cast(row_dtype, dict(db_row))  # asserts a type; proves nothing
```

```python
# GOOD: a model that actually checks the data
class CustomerRow(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    customer_id: str
    interval_seconds: int


row = CustomerRow.model_validate(dict(db_row))  # raises on a schema drift
```

`cast(...)` asserts a type. `model_validate(...)` proves one. Never the former.

## The bug class: a default on a required field

The bug is **not** the `.get(k, default)` spelling — that's a symptom. It is **a
default on a field that is required**. `dict.get("key", "default")` on a key the
team assumed was always present silently used the default forever.

**Required-vs-optional is the contract; syntax is a symptom.** Don't hunt
`.get(k, d)` / `or` / `if not` spellings — model the payload. Once the payload has
a real model, the required-vs-optional decision is *forced*: a default on a
required field becomes removable in any syntax, and a default on an optional field
becomes documented-correct.

```python
# BAD: the default masks a required field that was sometimes absent
interval = row.get("interval_seconds", 300)
```

```python
# GOOD: the model forces the decision
class CustomerRow(BaseModel):
    model_config = {"extra": "forbid"}

    interval_seconds: int  # required — absent input fails loud
    nickname: str | None = None  # optional — the default is the documented answer
```

## Empty string is not a value

ONE spelling of "absent": `None`.

- **required field** → reject blank (fail loud, same as missing)
- **optional field** → normalise blank → `None`

```python
class TicketInput(BaseModel):
    model_config = {"extra": "forbid"}

    ticket_key: str = Field(min_length=1)  # required — "" is rejected
    assignee: str | None = None

    @field_validator("assignee", mode="before")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        return v or None
```

**Exception that matters:** if a blank is currently **PERSISTED or FORWARDED** as
`""`, keep plain `str`. Changing it changes what gets written to DB columns — and
in one case nearly rendered the literal string `"None"` into an LLM prompt. Model
the *current* wire truth, not the tidier one.

## No opaque model fields

`Any` inside a model is the untyped dict one level down. **Ban the opaque VALUE,
not the container.**

| Banned                                    | Legal                                            |
| ----------------------------------------- | ------------------------------------------------ |
| `dict[str, Any]`, `Mapping[str, Any]`     | `Mapping[str, str]`, `dict[VectorKey, Result]`   |
| bare `dict`, bare `Mapping`, bare `Any`   | `Sequence[Model]` (prefer this)                  |

This does **not** contradict CORE PRINCIPLE #3 (immutable parameter types —
`Mapping`/`Sequence`, not `dict`/`list`). That rule is about the *container*, and
it stands. This rule is about the *value type* inside it. `Mapping[str, str]` is
both immutable-typed and fully typed — it satisfies both rules.

**Judgement over compliance.** Genuinely polymorphic fields (per-event-type
params, vendor-configurable attributes) get **DOCUMENTED**, not a fabricated
schema. A schema invented to satisfy a checker is a lie with a type annotation.

## No `**` splatting

```python
# BAD: unpacks the model back into an untyped dict
send_job(**job.model_dump())

# BAD: skips per-field checking at the ONE site that pins the contract
job = Job(**payload)
```

```python
# GOOD: name the fields
send_job(job_id=job.job_id, run_date=job.run_date)
job = Job.model_validate(payload)
```

**Logging is the ONLY exemption** — `log.bind(**ctx)` takes arbitrary context by
design. **SDK request-building is NOT exempt**: an SDK version bump can silently
change accepted params, and `**params` would hide the error.

## Model our side of a boundary, never the vendor's wire

Raw-JSON digging stays dict access — that *is* the parse. Only the RETURN becomes
a model. Don't mirror a vendor's nested JSON in Pydantic.

```python
def _normalize_issue(issue: Mapping[str, Any]) -> NormalizedTicket:
    """Vendor JSON in (dict access is the parse), our model out."""
    fields = issue["fields"]
    return NormalizedTicket(
        ticket_key=issue["key"],
        summary=fields["summary"],
        assignee=fields["assignee"]["displayName"] if fields.get("assignee") else None,
    )
```

## Every model starts from one shared config

A model's `model_config` must START FROM a single shared config object — not be
hand-written per model. A bare `ConfigDict(...)` on each model silently drops the
project's decisions and re-litigates strictness one model at a time; the day
someone forgets `extra="forbid"` is the day a renamed field goes silent.

```python
from pydantic import BaseModel, ConfigDict

# One place. Every model extends this; nobody re-decides strictness per model.
PYDANTIC_CONFIG = ConfigDict(
    extra="forbid",
    strict=True,
    validate_assignment=True,
    str_strip_whitespace=True,
)


class CustomerRow(BaseModel):
    model_config = PYDANTIC_CONFIG  # inherits every decision above

    customer_id: str
    interval_seconds: int
```

Extend it with `|` when one model genuinely needs a different setting — the shared
decisions still come along: `model_config = PYDANTIC_CONFIG | ConfigDict(...)`.
This shared object is the anchor for the `extra="forbid"` rule below: forbid lives
in ONE place, not re-typed (and re-forgettable) on every model.

## `str_strip_whitespace=True` corrupts verbatim content — opt out

The shared config sets `str_strip_whitespace=True` because it's right for
identifiers — a stray space around a name or email should die at the boundary. But
it SILENTLY strips leading/trailing whitespace from VERBATIM content — code, diffs,
chunk text, HTML — with no error and no log. It once stripped the leading
indentation off every code chunk entering a RAG index; nothing failed, the data was
just quietly wrong.

A field carrying verbatim content must opt OUT via the shared config:

```python
class CodeChunk(BaseModel):
    model_config = PYDANTIC_CONFIG | ConfigDict(str_strip_whitespace=False)

    content: str  # leading indentation is DATA — must survive verbatim
```

**Field-name smell list** — if a field is named any of these, it almost certainly
carries verbatim content and its model must set `str_strip_whitespace=False`:
`content`, `body`, `text`, `diff`, `snippet`, `patch`, `raw`, `chunk_text`,
`output`, `source`, `html`, `preview`.

## `extra="forbid"` everywhere — no exceptions

A schema change must be followed by a code change. `extra="ignore"` turns a
renamed field into silence.

A query **names its columns** — `SELECT customer_id, interval_seconds FROM …`,
**never `SELECT *`** — so the row's shape is one the code built end-to-end and no
unmodelled key can arrive.

**Operational consequence, stated explicitly:** for inbound messages this makes
**consumer-before-producer a hard DEPLOYMENT-ORDER requirement**. Deploy the
consumer that understands the new field before the producer that emits it. That is
a **deployment concern to solve in the deploy process** — it is NOT a reason to
weaken the code contract to `extra="ignore"`.

## Model where the shape is fixed, not where it's polymorphic

A generic client serves N tables with N shapes — unmodellable, and correctly so:

```python
# Generic client — dict return is correct here; the shape is genuinely unknown
async def get_item(self, table: str, key: Mapping[str, str]) -> dict[str, Any]: ...
```

The model belongs at the **domain store on top**, where the shape IS fixed:

```python
class StepResultStore:
    async def get(self, run_id: str) -> StepResultEnvelope:
        raw = await self._client.get_item("myapp-dev-steps", {"run_id": run_id})
        return StepResultEnvelope.model_validate(raw)  # shape is fixed HERE
```

Same for dynamic-keyed maps: the map is generic, the **value** is a model.

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
  passed through a command override / `containerOverrides`.
- **DB rows crossing into domain code** — a SQLAlchemy ORM model is genuinely
  typed and fine; a raw `dict(row)` cast to a TypedDict is the bug. Row dicts
  entering domain code get a real model.

**Every entry point parses its payload.** A Lambda `event`, an ECS env block, an
SQS message body, a Step Functions input — none of them are trusted dicts. The
boundary parse catches a malformed deploy or a renamed field *loudly* instead of
as a `KeyError` three calls deep.

## Genuine exemptions — codec-or-nothing

Exempt ONLY where the dict **IS the encoding being produced**:

- DynamoDB AttributeValue marshalling (`{"S": "…"}` / `{"N": "1"}`)
- Lambda response envelopes (`{"statusCode": 200, "body": …}`)

**External API responses and DynamoDB read payloads are trust boundaries and are
NOT exemptions** — they are listed above precisely because they must be parsed.

## Lambda event + ECS env — the boundary parse

```python
import uvloop
from typing import Any
from pydantic import BaseModel, Field
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

    model_config = {"extra": "forbid"}

    run_date: str = Field(alias="RUN_DATE")
    customer_ids: tuple[str, ...] = Field(default_factory=tuple, alias="CUSTOMER_IDS")


TASK_SETTINGS = TaskSettings()  # fails fast at import if RUN_DATE is unset
```

See [`config.md`](config.md) for the full `pydantic-settings` patterns and
[`serialization.md`](serialization.md) for crossing back out over a boundary.

## Internal contracts — default to Pydantic, dataclass is the allowlisted exception

**A dataclass validates NOTHING.** "It's already validated upstream, so skip
Pydantic" is not a reason — it just means the type is a hint nobody checks. In the
incident that produced this file, 85 of 98 internal dataclasses became Pydantic
models; the 13 survivors each had a proven STRUCTURAL reason, not a performance one.

**Default: a Pydantic `BaseModel`** — for data passed between modules,
business-logic return types, `domain/models/`, and already-validated data flowing
between features. If the concern is re-validating trusted data in a hot loop, use
`model_construct()` (see *Performance note*) to skip validation on a REAL model —
never drop to a dataclass for speed.

**Yes, validation costs something — and it is worth it.** A `BaseModel` is heavier
to construct than a `@dataclass` (roughly ~1–5μs per simple model; a dataclass is
near-free), and every boundary parse spends a little CPU a dataclass would not.
That cost buys the entire point of this file: a renamed key fails loud instead of
silently defaulting (incident 1 — silent billing), a credential can carry
`repr=False`, a schema drift is caught at construction rather than three calls
deep, and content survives verbatim or is rejected — never quietly corrupted
(incident 6). The failures this trades against were *invisible* and ran for months;
the microseconds are visible and bounded. When the microseconds genuinely matter,
the answer is `model_construct()` on a real model (validate once at the boundary,
skip re-validation on the trusted hot path) — not a dataclass that validates
nothing, ever. Security and robustness first; buy back the speed narrowly, where a
profiler proves you need it. → [`incidents.md`](incidents.md)

```python
# GOOD: default — a model even for an internal, already-validated contract
class TicketContext(BaseModel):
    """Context assembled for a ticket. A model, not a dataclass — it validates."""

    model_config = PYDANTIC_CONFIG  # the shared strict config

    ticket_key: str
    parent_summary: str | None
    siblings: tuple[str, ...]
```

**A `@dataclass(frozen=True, slots=True)` is allowed ONLY for a proven structural
reason, and each such use is allowlisted:**

- it holds a live, non-serializable object (a DB client / connection pool, an open
  socket, an aiobotocore client) that Pydantic would refuse to validate;
- it is a DI container wiring dependencies together;
- it carries a `TYPE_CHECKING`-only type a model field can't reference;
- it is the target of `dataclasses.replace()`.

"Already validated" is **not** on that list. If none of these apply, use a model.

```python
# ALLOWED (allowlisted): holds live clients a model can't validate
@dataclass(frozen=True, slots=True)
class StoreDeps:
    """DI container — holds live clients, not serializable data."""

    ddb: DynamoClient
    sqs: SqsClient
```

## Migration realities

### Blast radius is invisible to grep-by-name

Consumers rarely import the dtype — they just do `row["field"]` on whatever the
loader returned. Grepping for `row_dtype` finds the declaration and nothing else.
**That hidden subscript access is the work.** Trace the loader's return value
through its callers; don't trust a name search.

### Frozen models break four things

Freezing a model breaks `**` splatting, `del obj.field`, in-place mutation, and
`.get()`. Sweep for all four when you freeze. Use `model_copy(update=...)` for
post-hoc hydration:

```python
hydrated = envelope.model_copy(update={"resolved_at": now})
```

## Security — `Field(repr=False)` on credentials and PII

A model repr in a log line is a token leak. Credential/PII fields need
`Field(repr=False)`, and it must be verified **EMPIRICALLY**:

```python
class OrgSecrets(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    org_id: str = Field(repr=False)
    api_token: str = Field(repr=False)


assert repr(OrgSecrets(org_id="acme", api_token="•••••")) == "OrgSecrets()"
```

## Performance note

Pydantic validation costs ~1-5μs per simple model. Don't re-validate trusted data
inside hot loops; `model_construct()` bypasses validation when the source is
already validated.

## Don't

- ❌ `TypedDict` — anywhere, including test fixtures (`no-typeddict`).
- ❌ `typing.cast` — use `Model.model_validate(...)` (`no-cast`).
- ❌ `extra="ignore"` / `extra="allow"` — always `forbid`.
- ❌ `SELECT *` — name the columns.
- ❌ A default on a required field.
- ❌ `Any` / bare `dict` / bare `Mapping` as a model field type.
- ❌ `f(**model.model_dump())` — logging is the only `**` exemption.
- ❌ Mirroring a vendor's nested JSON in Pydantic — model our side only.
- ❌ Pydantic inside hot loops over already-validated data.

## Enforcement

Every rule on this page is a checker, not prose — a rule in prose gets violated;
a rule in a checker holds.

- `checkers/pydantic_contract.py` — AST gate: `no-typeddict`, `no-cast`,
  `extra-forbid`, `masking-default`, `opaque-annotation`, `splat`,
  `select-star`, `secret-repr`. Run it behind
  `regression-gates/baseline_gate.py` so it lands regression-only and ratchets
  to zero.
- mypy strict — catches `dict[str, Any]` leakage at function signatures.

Full matrix + wiring recipe → [`enforcement.md`](enforcement.md).
