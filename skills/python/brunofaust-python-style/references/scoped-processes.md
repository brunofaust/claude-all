# Scoped global processes — run-for-one + idempotency supersession

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a
> condensed summary; this file holds the full depth.

Every "global" process — a Lambda or ECS job that runs across **all** tenants /
customers / accounts — must also be runnable for a **single entity or a group**.
The scope is a first-class, validated parameter of the job, not a code edit.

## Why this rule exists

Two payoffs, one mechanism:

1. **e2e / integration test isolation.** A test seeds data for *its own* tenant,
   then runs the real job **scoped to that tenant only**. Parallel tests under
   `pytest-xdist` never touch each other's rows, and a test never has to wait for
   (or get polluted by) an all-tenant sweep. This is the operational half of the
   test-isolation rules in [`testing.md`](testing.md) — isolation in the *tests*
   only holds if the *processes the tests drive* can be scoped.
2. **Production support.** When one customer needs a re-run (bad upstream file,
   a backfill, a hotfix replay), you scope the existing job to that customer
   instead of re-processing the entire fleet or writing a one-off script.

If a global job can *only* run for everyone, neither is possible: tests collide and
support is forced into bespoke scripts that drift from the real code path.

## The scope parameter — validated, optional, plural

Scope is part of the job's input contract, so it is parsed with Pydantic at the
boundary (see [`data-modeling.md`](data-modeling.md)). Absent scope = "all" (the
global run). A present scope narrows to one or a group.

```python
from pydantic import BaseModel, Field


class JobScope(BaseModel):
    """Optional narrowing of a global job to specific entities.

    Empty / absent → run for ALL customers (the global sweep).
    Populated → run only for the listed customers (single or group).
    """

    model_config = {"extra": "forbid", "frozen": True}

    customer_ids: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def is_global(self) -> bool:
        """True when the job covers every customer (no narrowing)."""
        return not self.customer_ids


class DailyRollupEvent(BaseModel):
    """Validated entry payload for the daily rollup Lambda."""

    model_config = {"extra": "forbid", "frozen": True}

    run_date: str  # ISO date — the idempotency period
    scope: JobScope = Field(default_factory=JobScope)
```

Rules:

- **Scope is always a set/tuple, never a lone id.** "single" is just a group of
  one — one code path, no special-case branch for "one customer".
- **Absent = global.** Don't invent a sentinel like `customer_id="ALL"`; an empty
  scope *is* the global run.
- **Resolve the work-list from scope.** `targets = scope.customer_ids or await
  list_all_customers()`. The fan-out body is identical whether scoped or global.
- **Never share a foreign key across tenants.** When the job seeds or joins data,
  every child row resolves to a customer that belongs to the *same* tenant — see
  the FK-isolation rule in [`testing.md`](testing.md). A scoped run must not reach
  a row owned by a tenant outside its scope.

## DynamoDB idempotency must include the scope

A naive idempotency key (`job#run_date`) is **wrong** for a scoped job: it either
lets a global run and a customer run collide on one key, or it ignores scope and
double-processes. The key — and the supersession check below — must account for
*which entities a run covers*.

Record one item **per covered entity**, plus one marker for the global sweep:

| Run kind        | Items written (idempotency table)                          |
| --------------- | ---------------------------------------------------------- |
| Global (no scope) | one `GLOBAL` marker: `job#run_date#GLOBAL`                |
| Scoped (group)  | one per customer: `job#run_date#customer#<id>` for each id |

Writing **per-entity** items (not one item for the whole scoped batch) is what
makes supersession and partial re-runs checkable at the granularity of a single
customer.

```python
from enum import StrEnum


class RunState(StrEnum):
    IN_PROGRESS = "in_progress"
    DONE = "done"
```

## Supersession — a global run blocks the customer-specific run

The critical rule: **a global run (no scope) supersedes any customer-scoped run
for the same period.** If customer `C` is already covered by a `GLOBAL` run for
`run_date`, a later run *scoped to `C`* must be **blocked** — `C`'s work is already
done (or in flight) under the umbrella run, and re-doing it risks double effects.

The check therefore tests **two** keys before claiming a customer, in order:

1. **Umbrella key** `job#run_date#GLOBAL` — if it exists (in progress or done),
   the customer is already covered → **block / skip**. This is the supersession.
2. **Per-customer key** `job#run_date#customer#<id>` — if it exists, this exact
   customer already ran → skip (ordinary idempotency).
3. Neither exists → conditionally `PutItem` the per-customer key and process.

```python
async def claim_customer(
    table: IdempotencyTable,
    job: str,
    run_date: str,
    customer_id: str,
) -> bool:
    """Try to claim one customer for processing.

    Returns True if the caller may process the customer, False if it is already
    covered (by a GLOBAL umbrella run or a prior per-customer run).

    Raises:
        ClientError: on a DynamoDB error other than the conditional-check failure.
    """
    # 1. Supersession — a GLOBAL run for this period already covers everyone.
    if await table.exists(f"{job}#{run_date}#GLOBAL"):
        log.info("superseded_by_global", job=job, run_date=run_date, customer=customer_id)
        return False

    # 2 + 3. Atomically claim the per-customer key (attribute_not_exists guard).
    try:
        await table.put_if_absent(
            key=f"{job}#{run_date}#customer#{customer_id}",
            state=RunState.IN_PROGRESS,
        )
    except ConditionalCheckFailed:
        return False  # another worker / a prior run already claimed this customer
    return True
```

The **global** run claims the umbrella key the same way, and should itself be
guarded so two global runs don't overlap:

```python
async def claim_global(table: IdempotencyTable, job: str, run_date: str) -> bool:
    """Claim the GLOBAL umbrella for a period; False if one already ran."""
    try:
        await table.put_if_absent(
            key=f"{job}#{run_date}#GLOBAL",
            state=RunState.IN_PROGRESS,
        )
    except ConditionalCheckFailed:
        return False
    return True
```

### Edge: customer already ran, then a global run starts

A per-customer run for `C` completes, *then* a global sweep starts for the same
period. The global run's per-customer fan-out hits step 2 for `C` (`...#customer#C`
exists) and skips `C` — no double processing — while still covering everyone else.
So supersession is **asymmetric and safe**: GLOBAL blocks later customer runs;
an earlier customer run is simply absorbed (skipped) by a later GLOBAL.

### Don't collapse the two checks into one

A single key (e.g. hashing the scope set) cannot express "GLOBAL covers C" — the
hash of `{C}` differs from the hash of "all". You need the explicit umbrella key
plus per-customer keys. Resist the urge to "simplify" to one composite key; the
supersession semantics are the whole point.

## Test isolation tie-in

In e2e tests, drive the real handler with a **scoped** event so the test only ever
touches its own seeded tenant:

```python
@pytest.mark.e2e
async def test_daily_rollup_for_single_customer() -> None:
    """Rollup scoped to one freshly-seeded customer stays isolated under xdist."""
    customer = await seed_customer()  # dynamic id, owns its own child rows
    await seed_orders(customer_id=customer.id, count=3)

    event = DailyRollupEvent(run_date="2026-06-25", scope=JobScope(customer_ids=(customer.id,)))
    result = await main(event.model_dump())

    rollup = await get_rollup(customer_id=customer.id)
    assert rollup.order_count == 3, f"unexpected rollup: {rollup!r}"
```

Because the job is scoped to a per-test customer id, the assertion is immune to
whatever the other xdist workers are doing — no shared rows, no GLOBAL sweep
racing the test. See [`testing.md`](testing.md) for the seeding / dynamic-id /
per-tenant-FK rules this depends on.

## Checklist

- [ ] Every global job accepts an optional, validated scope (plural ids; absent = all).
- [ ] One code path for scoped vs global — `scope or list_all()`, no "single" branch.
- [ ] Idempotency records one item per covered entity + a `GLOBAL` umbrella marker.
- [ ] Customer-scoped claim checks the `GLOBAL` umbrella **first** (supersession), then the per-customer key.
- [ ] Global claim is itself guarded against a second concurrent global run.
- [ ] No foreign key resolves across tenants; a scoped run never reaches another tenant's rows.
- [ ] e2e tests drive the handler scoped to their own seeded tenant.
</content>
</invoke>
