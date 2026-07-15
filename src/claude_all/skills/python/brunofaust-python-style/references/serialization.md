# Serialization — crossing a boundary with a model

**Decision rule:** a model that looks right in memory can still change the bytes on
the wire. When you replace a dict with a Pydantic model at a boundary, the
serialized output MUST stay byte-identical — and you prove it with a round-trip
test, not by reading the code.

A "boundary" is anywhere the payload leaves the process: a Step Functions state
output, an SQS message body, a DynamoDB item, an HTTP response, a Lambda return
value. In-memory equality is not evidence. Bytes are.

## Rule 1 — dump at every boundary, prove the shape didn't move

`model_dump(mode="json")` is the boundary form: JSON-native types only
(`datetime` → ISO string, `UUID` → str, `Decimal` → str/float, `Enum` → value).
Plain `model_dump()` gives you Python objects that most encoders choke on.

```python
# BAD: python-mode dump leaks datetime/UUID/Enum objects onto the wire
payload = task.model_dump()
await sqs.send_message(QueueUrl=url, MessageBody=orjson.dumps(payload).decode())

# GOOD: json-mode dump at the boundary
payload = task.model_dump(mode="json")
await sqs.send_message(QueueUrl=url, MessageBody=orjson.dumps(payload).decode())
```

The deploy hazard: an **already-in-flight** Step Functions execution was started
by the OLD code and its state carries the OLD dict. The NEW code must still parse
it. A dict→model change is only safe if both directions hold — the new model
parses the old payload, and the new dump equals the old dict.

## Rule 2 — `orjson.dumps` cannot serialize a Pydantic model

This skill mandates orjson over stdlib `json`, so this bites on the first line.
orjson serializes native types only; it has no idea what a `BaseModel` is.

```python
# BAD: TypeError: Type is not JSON serializable: TaskPayload
orjson.dumps(task)

# GOOD: dump first, then encode
orjson.dumps(task.model_dump(mode="json"))
```

Do **not** reach for `orjson.dumps(task, default=...)` to paper over it — a
`default` hook hides the missing boundary dump and will silently pick a different
shape (e.g. `__dict__`) than `model_dump` would.

## Rule 3 — aliases silently rename wire keys

An alias exists precisely because the wire key is not a legal Python attribute
name — `class`, `from`, `id`, `type` are the usual suspects. The attribute name is
what `model_dump()` emits **by default**, which is not the wire key.

```python
from pydantic import BaseModel, ConfigDict, Field


class Attachment(BaseModel):
    """Wire payload for an attachment; `class` is a Python keyword."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    attachment_class: str = Field(alias="class")
    source_url: str = Field(alias="from")
```

```python
# BAD: emits {"attachment_class": ..., "source_url": ...} — consumers see NO `class` key
orjson.dumps(att.model_dump(mode="json"))

# GOOD: emits {"class": ..., "from": ...} — matches the pre-migration dict
orjson.dumps(att.model_dump(mode="json", by_alias=True))
```

Pick ONE convention per boundary and state it in the model's docstring. Mixed
`by_alias` usage across two call sites is how half the consumers break.

## Rule 4 — `exclude_none` decides absent vs null

TypedDict `NotRequired` means the key is **absent**. A model field defaulting to
`None` means the key is present with value `null`. Those are different bytes and
different downstream behaviour (`if "x" in payload` vs `payload["x"] is None`, and
DynamoDB stores a `NULL` attribute rather than nothing at all).

```python
class Ticket(BaseModel):
    ticket_key: str
    assignee: str | None = None


t = Ticket(ticket_key="TICK-1")

t.model_dump(mode="json")                     # {"ticket_key": "TICK-1", "assignee": None}
t.model_dump(mode="json", exclude_none=True)  # {"ticket_key": "TICK-1"}
```

Replacing a `NotRequired[str]` TypedDict field with `str | None = None` and
dumping without `exclude_none=True` flips absent → null for every consumer at
once. Choose deliberately and write down why:

- **`exclude_none=True`** — reproducing `NotRequired` omission semantics; the
  consumer distinguishes "not sent" from "explicitly cleared".
- **default (keep nulls)** — the consumer needs an explicit `null` to overwrite a
  stored value (PATCH-style merges, DynamoDB attribute clears).

`exclude_none` is not a tidiness setting. It is part of the contract.

## Rule 5 — lax mode will not coerce `int` → `str`

Pydantic v2's default ("lax") mode coerces `str` → `int`, not the reverse. A store
that round-trips ids "stringly" hands you a number where the code expects text.
DynamoDB is the classic: written as `N`, read back as a numeric, consumed as `str`.

```python
# BAD: ValidationException / ValidationError — the item's `attempt` came back as N
Progress.model_validate(item)

# GOOD: cast at the read boundary, where the store's typing is known
Progress.model_validate({**item, "attempt": str(item["attempt"])})
```

Keep the explicit casts you had before the migration. Do **not** "fix" this with
`model_config = ConfigDict(coerce_numbers_to_str=True)` on a boundary model — it
makes the model accept a shape the producer should never have sent, and hides the
real drift.

## Rule 6 — `model_construct()` bypasses validation

`model_construct()` skips validators, coercion, alias resolution, and defaults
logic. It is for data from a **genuinely trusted** source — a value your own
process validated microseconds ago, a fixture, a hot loop over already-validated
rows.

```python
# BAD: "validation is slow at the boundary" — this is exactly where you need it
event = RollupEvent.model_construct(**raw_lambda_event)

# GOOD: validate at the boundary; construct only downstream of it
event = RollupEvent.model_validate(raw_lambda_event)
rows = [Row.model_construct(**r) for r in already_validated_rows]  # hot loop, trusted
```

Validation costs ~1-5μs per simple model. That is never the reason a boundary is
slow. `model_construct()` at a trust boundary is not an optimization — it is an
unvalidated `dict` wearing a model's type hint.

## Round-trip proof

The **only** acceptable evidence that a wire shape did not change is a test
asserting the pre-migration dict equals the post-migration
`model_dump(mode="json")`. Pin the expected dict as a literal — copied from a real
captured payload, never generated from the model itself (a dump compared against a
dump proves nothing).

```python
import orjson
import pytest

from myapp.domain.models import Attachment

# Captured verbatim from a myapp-dev-worker Step Functions execution BEFORE the
# dict -> model migration. Do not regenerate — this is the external truth.
LEGACY_PAYLOAD: dict[str, object] = {
    "class": "image",
    "from": "https://example.com/a.png",
}


def test_model_dump_matches_legacy_wire_shape() -> None:
    """The post-migration dump must be byte-identical to the legacy dict."""
    att = Attachment.model_validate(LEGACY_PAYLOAD)
    assert att.model_dump(mode="json", by_alias=True) == LEGACY_PAYLOAD
    assert orjson.dumps(att.model_dump(mode="json", by_alias=True)) == orjson.dumps(
        LEGACY_PAYLOAD
    )


def test_model_parses_in_flight_legacy_payload() -> None:
    """An execution started by the old code must still parse after the deploy."""
    att = Attachment.model_validate(LEGACY_PAYLOAD)
    assert att.attachment_class == "image"
```

Both directions matter: **parse** the old payload (in-flight executions) and
**emit** the old payload (downstream consumers). One without the other is a
half-proof.

## Checklist before shipping a dict→model change at a boundary

1. Captured a **real** payload from the running system and pinned it as a literal.
2. Round-trip test asserts `model_dump(mode="json", ...) == captured_dict`.
3. Reverse test asserts the new model parses the captured (old) payload — for
   in-flight Step Functions executions and messages already sitting in a queue.
4. Every `orjson.dumps(model)` replaced with `orjson.dumps(model.model_dump(mode="json"))`.
5. `by_alias=True` decided per boundary and applied at **every** call site.
6. `exclude_none` decided per boundary, with the absent-vs-null reason documented.
7. Explicit `str()`/`int()` casts kept for stringly-typed store reads.
8. No `model_construct()` anywhere data enters from outside the process.

## Don't

- Compare a dump to a dump — the fixture must come from outside the code.
- Add `default=` to `orjson.dumps` to make a model encodable.
- Mix `by_alias=True` and `by_alias=False` across call sites for one model.
- Let `exclude_none` be decided by whoever wrote the line first.
- Loosen a boundary model's config (`coerce_numbers_to_str`, `extra="allow"`) to
  make a wire mismatch go away — fix the producer or cast at the read.
- Use `model_construct()` for speed at a trust boundary.

## See also

- [`data-modeling.md`](data-modeling.md) — where the boundary is, and which type belongs there.
- [`testing.md`](testing.md) — fixtures pinned to external truth, not to the code.
