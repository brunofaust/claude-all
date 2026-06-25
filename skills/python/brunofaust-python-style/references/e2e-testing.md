# E2E / integration testing on shared infra (multi-tenant)

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a
> condensed summary; this file holds the full depth.
>
> **Suggested pattern, not a hard rule.** This is how to run a parallel e2e /
> integration suite for a multi-tenant system against **one** shared backing stack
> (one DB, one queue, one state machine, one set of mock servers) without the suite
> going flaky. Adopt the pieces that fit; the data-isolation half is the
> non-negotiable core, the rest are remedies for specific shared-infra failures.

## Core principle — isolate data, accept shared infrastructure, never confuse the two

Two *different* classes of flakiness, two *different* remedies. Diagnose every
failure as one or the other before you touch it:

| Class                  | Cause                                                                                     | Remedy                                                                  |
| ---------------------- | ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| **Data contention**    | Test A's rows poison test B (shared seed, hard-coded id, cross-tenant FK)                  | **Data isolation** — every test owns its own tenant + all its rows      |
| **Infra contention**   | Parallel workers fight over the *one* shared DB / queue / state machine / mock server      | **Serialization or robustness** — drain-to-own, concurrency-safe mocks, phased runs |

- **Data isolation** = every test owns its own tenant and all that tenant's rows.
  This kills the entire "test A poisons test B" class. It is non-negotiable — the
  four rules live in [`testing.md`](testing.md) (dynamic ids, per-test ownership,
  FKs never cross tenants, runs under `pytest-xdist`).
- **Shared infrastructure** (one DB instance, one queue, one state machine, one set
  of mock servers) is shared across parallel workers — you can't afford a stack per
  test. Sharing causes a *different* class of flakiness (contention / ordering) that
  **data isolation does not fix**. The remedy is serialization or robustness, per
  the sections below.

The trap is misdiagnosis: spending hours hardening data isolation when the real
failure was a single-threaded mock server, or vice-versa. Identify the class first.

## 1. No shared seed of tenant data — one factory creates everything

- The global DB seed contains **only global reference data** — rows with no tenant
  id, shared by nature (plan catalogue, model/provider/connector-type definitions,
  enum lookups).
- **Zero tenant rows in the seed.** Every test calls one factory,
  `create_tenant(...)`, that creates the entire tenant graph in one place (the
  tenant, its connectors, projects, workflows, personas, status mappings, billing
  period, credits, secrets, seeded records).
- **One place to add or change tenant data.** Future tenant data goes into the
  factory, not scattered across tests. This is the operational expression of
  [`testing.md`](testing.md) rule 2 ("each test owns its data") — the factory is
  *how* a test cheaply owns a whole realistic tenant.

```python
# ❌ BAD — a global "test tenant" seeded once at migrate time, reused everywhere
# (every test reads/writes the same rows → contention under xdist)

# ✅ GOOD — global seed = reference data only; each test mints its own tenant graph
async def test_workflow_runs_for_fresh_tenant() -> None:
    tenant = await create_tenant()  # full graph, dynamic ids, owns its own rows
    ...
```

## 2. Customization via factory parameters, not manual DB writes in tests

Every variation a test needs is a `create_tenant` parameter — the edge/denied/
exhausted start state is **provisioned at creation**, not poked into the DB by the
test afterwards.

```python
# ✅ provision the denied path at creation
tenant = await create_tenant(plan_minutes_consumed=1000)  # already over budget
tenant = await create_tenant(wallet_balance_cents=1)      # one unit from empty
tenant = await create_tenant(plan_id="free")              # plan-gated path
```

- Manual DB mutation inside a test is the **rare exception**, allowed only when the
  test is *about* a state transition that happens mid-run (e.g. a wallet draining to
  zero *during* execution). Prefer setting the start state via a param (wallet =
  `0.01`) and letting the run consume it.
- Keeps the "what start states exist" knowledge in one typed place instead of as
  ad-hoc `UPDATE`s smeared across the suite.

## 3. Randomize ID sequences after migrate + seed

After `alembic upgrade head` and the reference seed, `ALTER SEQUENCE … RESTART WITH
<random-high>` for **every** sequence. Each run's `create_tenant` rows then get
fresh, non-deterministic ids.

```python
async def randomize_sequences(conn: AsyncConnection) -> None:
    """Restart every serial sequence at a high random offset post-seed.

    Forces dynamic ids: any stale literal id in a payload fails deterministically
    instead of coincidentally matching a low auto-increment value on some runs.
    """
    rows = await conn.execute(text("SELECT sequencename FROM pg_sequences WHERE schemaname = 'public'"))
    for (seq,) in rows.fetchall():
        offset = randbelow(900_000) + 100_000  # 6-digit high start, per run
        await conn.execute(text(f'ALTER SEQUENCE "{seq}" RESTART WITH {offset}'))
```

**Why it's a correctness gate, not cosmetics:** no test *can* hard-code an id, and
any stale literal id (a payload still carrying `tenant_id=1` / `step_id=1`) fails
**deterministically** instead of coincidentally matching a low auto-increment value
on some runs. It turns a "passes on my machine, flaky in CI" bug into a hard,
every-run failure you can actually fix. Pairs with [`testing.md`](testing.md) rule 1
(dynamic ids).

## 4. Mock servers must be concurrency-capable

A single-threaded mock (`http.server.HTTPServer`) **serializes** requests; under N
parallel workers, callers queue and blow their client timeouts — surfacing as
"flaky e2e" that is really a mock that can't serve concurrent workers.

```python
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from threading import Lock

_state_lock = Lock()  # guard shared in-memory state across handler threads


class MockHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        with _state_lock:
            ...  # mutate shared state under the lock only


# ✅ ThreadingHTTPServer — one thread per request; HTTPServer would serialize them
server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
```

Use `ThreadingHTTPServer` (or any concurrency-capable server) **plus a lock**
guarding shared in-memory state. A surprising amount of "flaky e2e" is exactly this.

## 5. Draining a shared queue — filter-to-own, never steal

When tests share one real queue, each test drains **only its own** messages (match
on its tenant / connector id) and leaves foreign messages untouched.

- **Never delete or hold another test's message.** Processing a foreign message is
  wrong twice: it's another test's work, *and* the cross-tenant config isn't
  reachable from this test's setup (e.g. that connector's URL isn't remapped to the
  mock → a real connection error).
- **Set the drain's first-message timeout above the queue's visibility timeout**, so
  a sibling worker that momentarily receives-then-releases your message can't starve
  you out of it.

```python
async def drain_own(queue: Queue, *, tenant_id: str, visibility_timeout: float) -> list[Message]:
    """Receive only this tenant's messages; release anything foreign untouched."""
    mine: list[Message] = []
    # first-message wait must exceed the queue's visibility timeout (see above)
    deadline = visibility_timeout * 1.5
    async for msg in queue.receive(wait=deadline):
        if msg.attributes.get("tenant_id") == tenant_id:
            mine.append(msg)
        else:
            await msg.release()  # ❌ never delete/hold — it belongs to another test
    return mine
```

This is the queue-level instance of the FK-isolation rule in
[`testing.md`](testing.md): a test never reaches another tenant's work.

## 6. Timeouts and fail-closed paths

Code that swallows an error and "continues" (e.g. a prefetch probe timing out →
treated as "no work") is **invisible by design** — and one such bug can silently
stop *all* tenants. Two rules:

1. **Log the effective budget before the loop** so you never debug a timeout blind
   ("how long did it actually wait?" must be answerable from the logs).
2. **Publish every fail-closed event to a monitored channel** (a global warning
   queue / metric), not just a local log line that never escapes the worker.

```python
log.info("prefetch_budget", timeout_s=budget, tenant_id=tenant_id)  # rule 1
try:
    work = await asyncio.wait_for(probe(), timeout=budget)
except TimeoutError:
    await warnings_queue.publish(FailClosed(reason="prefetch_timeout", tenant_id=tenant_id))  # rule 2
    work = []  # fail closed — but loudly, on a channel a test/alarm can assert on
```

**Per-environment timeout tuning belongs in config**, not in the code. The e2e host
(many workers + mocks + an AWS emulator on one machine) legitimately needs a longer
probe timeout than prod — set it via the env channel the in-process code actually
reads (see § 7). This is the no-silent-error-swallowing rule from
[`error-handling.md`](error-handling.md) applied to timeouts.

## 7. Config must reach in-process code *before* the settings cache builds

If code reads settings via a cached `get_settings()`, the value must be present in
the environment **before** the cache is first built (load it in the root `conftest`
or a `.env` the test process reads at import). A late `os.environ.update(...)` after
the cache exists silently has **no effect** — the classic "I set it but it didn't
take" trap.

```python
# ❌ BAD — cache already built from the old env; this update is a no-op
def test_x():
    os.environ["PREFETCH_TIMEOUT_S"] = "30"  # too late — get_settings() cached at import
    ...

# ✅ GOOD — set it before the process imports anything that calls get_settings()
# tests/conftest.py (root) or tests/pytest.env, loaded by pytest-dotenv at startup
```

See [`config.md`](config.md) for the Settings-singleton rules this depends on.

## 8. xdist scheduling — pick the dist mode at *parse* time

The dist mode is **locked at parse time** — a `conftest` hook cannot reliably flip
the scheduler later (`config.option.dist` in `pytest_configure` is already too late).
Set it in `addopts` or on the CLI.

| Dist mode    | `xdist_group` markers | Use when                                                       |
| ------------ | --------------------- | -------------------------------------------------------------- |
| `worksteal`  | **ignored**           | Default — tests are truly isolated, scatter freely (fastest)   |
| `loadgroup`  | **honored**           | You genuinely need grouped tests pinned to one worker          |

After true data isolation, **most grouping becomes unnecessary**. The residue is
tests that drive a pipeline *in-process* and so contend on the shared queue / state
machine — those still want serialization (see § 9 for the cleaner phased approach,
and [`testing.md`](testing.md) for why `xdist_group` is a diagnostic, not a tool).

## 9. Phased execution for cross-tenant / global processes (one pytest pass)

Global operations — a scheduler tick that scans *all* tenants — are inherently
incompatible with concurrent per-tenant tests: they sweep up half-created tenants.
They must run **alone, on a known DB state**. Rather than a second pytest invocation,
do it in a **single pass** with a tiny plugin.

> If the global job itself takes an optional scope param, prefer scoping it to the
> test's own tenant — see [`scoped-processes.md`](scoped-processes.md). Phasing is
> for the genuinely *un-scopeable* global sweep that must see a quiescent DB.

The plugin has four parts:

1. **A phase marker.** `@pytest.mark.phase(n)` (int ≥ 1); unmarked ⇒ phase 0.
   `pytest_collection_modifyitems` stable-sorts items ascending by phase. Phase 0
   runs first as a **full parallel** sweep, then phase 1, 2, … **Within** a phase
   tests still distribute across workers — phasing serialises *between* phases,
   never within one.
2. **A cross-worker barrier.** No worker starts phase `N+1` until *every* worker has
   drained phase `N`:
   - Compute the **expected count per phase** once at collection, written to a
     shared file every worker reads.
   - On each item's completion, increment `completed[phase]` in a shared on-disk
     counter under a **brief** filelock (guarding only the read-modify-write).
   - Before running an item, **poll** until every lower phase hits its expected
     count. The lock is **never held across the poll** — that would deadlock; it
     guards only the mutation.
   - Honour an overall **barrier timeout** (a pytest ini option, e.g.
     `phase_barrier_timeout`) and **fail loud** on expiry — a stuck phase is a hard
     error, not a silent hang.
3. **Per-phase reset — a `{phase: fn}` mapping, injected by the project.** The
   generic plugin never knows *how* to reset; the project hands it a mapping from
   phase number to a reset callable, set in `pytest_configure` (not a per-mark flag,
   not a module global). After the barrier confirms phase `N-1` drained and
   **before** phase `N` runs, **exactly one worker** (the first across the boundary,
   chosen under a lock) calls `config._phase_reset[N]`. Phases absent from the map —
   including phase 0 — do **not** reset. It is *always* a per-phase mapping; there is
   deliberately **no single-callable-for-all-phases variant** (different phases need
   different resets — clear billing state before one, cross-tenant locks before
   another).
4. **Shipped as a named plugin** so it's trivially disabled (`-p no:phasing`),
   leaving collection/ordering unchanged and no barrier/reset running.

```python
# tests/e2e/conftest.py  (PROJECT) — inject the per-phase reset mapping.
# The plugin stays generic; only the project knows how to reset its own backing infra.
def pytest_configure(config: pytest.Config) -> None:
    config._phase_reset = {
        2: reset_billing_state,     # a DISTINCT fn per phase — never one-fn-for-all
        3: reset_global_scheduler,  # clear cross-tenant locks before the all-tenant sweep
    }
```

```python
# tests/e2e/phasing.py  (GENERIC PLUGIN) — orchestration only; `-p no:phasing` disables it.
# Module-level names avoid the `_` prefix (use __all__) per the visibility rule.
import pytest

__all__ = ["PHASE_MARK", "pytest_configure", "pytest_collection_modifyitems", "pytest_runtest_protocol"]

PHASE_MARK = "phase"


def pytest_configure(config: pytest.Config) -> None:
    """Declare the marker; the project's conftest supplies config._phase_reset."""
    config.addinivalue_line("markers", f"{PHASE_MARK}(n): ordered phase n (int ≥ 1; default 0)")


def phase_of(item: pytest.Item) -> int:
    """Phase number of an item; unmarked tests are phase 0."""
    marker = item.get_closest_marker(PHASE_MARK)
    return int(marker.args[0]) if marker else 0


@pytest.hookimpl(trylast=True)  # run AFTER the suite's other modifyitems hooks
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Order the whole pass by phase ascending; record per-phase expected counts."""
    items.sort(key=phase_of)
    counts: dict[int, int] = {}
    for item in items:
        counts[phase_of(item)] = counts.get(phase_of(item), 0) + 1
    write_expected_counts(config, counts)  # shared file, read by every worker


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> object:
    """Gate each item behind the barrier; run the phase's reset once on entry."""
    phase = phase_of(item)
    await_lower_phases_drained(item.config, phase)         # poll; brief lock per read
    if claim_phase_entry(item.config, phase):              # exactly one worker wins
        reset = getattr(item.config, "_phase_reset", {}).get(phase)
        if reset is not None:
            reset()                                        # project fn, mid-run-safe
    outcome = yield
    increment_completed(item.config, phase)                # brief filelock around RMW
    return outcome.get_result()
```

Each reset fn must be **mid-run-safe**: when it touches a sequence use
`GREATEST(<seq>, <floor>)` so it never lowers a sequence below already-committed rows
from a concurrent worker. This keeps the parallel per-tenant tests and the run-alone
all-tenant tests in **one** `pytest -n auto` pass — no second invocation — ordered,
quiesced between phases, with the reset action living in the project that owns the
infra, not in the plugin.

### The barrier helpers — a file-counter shared across xdist workers

The skeleton above calls four helpers. Here they are, minimal and complete. The key
fact: **xdist exports `PYTEST_XDIST_TESTRUNUID`** (identical for every worker in a
run), so all workers agree on one scratch dir; each phase is a counter in a shared
JSON file, guarded by a `filelock` only around the read-modify-write.

```python
# tests/e2e/phasing.py (continued)
import json, os, tempfile, time
from pathlib import Path
from filelock import FileLock

# In production, read these from pytest ini options (phase_barrier_timeout /
# phase_poll_interval), not module constants — no hardcoded config.
BARRIER_TIMEOUT, POLL = 300.0, 0.5


def phase_dir(config: pytest.Config) -> Path:
    """One scratch dir shared by every xdist worker in this run."""
    run = os.environ.get("PYTEST_XDIST_TESTRUNUID", "serial")  # same for all workers
    d = Path(tempfile.gettempdir()) / f"pytest-phasing-{run}"
    d.mkdir(exist_ok=True)
    return d


def write_expected_counts(config: pytest.Config, counts: dict[int, int]) -> None:
    """Persist tests-per-phase once. Every worker collects the FULL suite → identical totals."""
    path = phase_dir(config) / "expected.json"
    with FileLock(f"{path}.lock"):
        if not path.exists():
            path.write_text(json.dumps({str(k): v for k, v in counts.items()}))


def increment_completed(config: pytest.Config, phase: int) -> None:
    """Atomically tally one finished test against its phase, across all workers."""
    path = phase_dir(config) / "completed.json"
    with FileLock(f"{path}.lock"):
        done = json.loads(path.read_text()) if path.exists() else {}
        done[str(phase)] = done.get(str(phase), 0) + 1
        path.write_text(json.dumps(done))


def await_lower_phases_drained(config: pytest.Config, phase: int) -> None:
    """Block until EVERY lower phase hit its expected count across ALL workers."""
    if phase == 0:
        return  # phase 0 is the parallel baseline — nothing precedes it
    expected = json.loads((phase_dir(config) / "expected.json").read_text())
    completed_path = phase_dir(config) / "completed.json"
    deadline = time.monotonic() + BARRIER_TIMEOUT
    while True:
        done = json.loads(completed_path.read_text()) if completed_path.exists() else {}
        if all(done.get(str(p), 0) >= expected.get(str(p), 0) for p in range(phase)):
            return  # every prior phase fully drained on every worker → proceed
        if time.monotonic() >= deadline:
            raise TimeoutError(f"phase {phase} barrier: prior phases not drained in {BARRIER_TIMEOUT}s")
        time.sleep(POLL)  # fail loud on timeout, never hang silently


def claim_phase_entry(config: pytest.Config, phase: int) -> bool:
    """True for exactly ONE worker per phase — the first to create the marker."""
    marker = phase_dir(config) / f"entered-{phase}"
    with FileLock(f"{marker}.lock"):
        if marker.exists():
            return False
        marker.write_text("1")
        return True
```

That's the whole barrier: `write_expected_counts` (called once at collection from
`pytest_collection_modifyitems`), `increment_completed` (after each test), and
`await_lower_phases_drained` (before each test) together guarantee no worker enters
phase `N` until every phase `< N` test has finished on *every* worker.
`claim_phase_entry` then elects the single worker that runs `config._phase_reset[N]`.
(If a reset must *complete* before siblings proceed, have the winner also write a
`reset-{phase}.done` marker and have the others poll for it before their first test.)

## 10. Fixtures / payloads agree with reality, not the code's assumptions

Static payload fixtures rot: `base_url` vs `url`, a hard-coded `step_id=1`. The
randomized ids of § 3 surface this immediately.

- **Prefer building inputs from the factory's returned context** (`tenant.connectors[0].url`)
  over a templated static payload.
- If you must template a static payload, **rewrite every tenant-scoped id field**,
  and treat a field-name mismatch as a **real bug to fix, not paper over** — the
  handler and the fixture disagree about the contract.
- **The systemic fix for this whole class is Pydantic validation at the boundary**
  (Lambda event / queue message / service entrypoint env): malformed input
  (`project_key=""`, missing `url`) fails fast with a clear error *at the handler*
  instead of a deep `ForeignKeyViolation` / `KeyError` later. See
  [`data-modeling.md`](data-modeling.md) and [`mock-drift-sweep`](../../generic/mock-drift-sweep/SKILL.md).

## 11. Verifying a flaky-test fix (method)

A concurrency fix is **not proven by one green run.**

1. **Reproduce, then isolate the variable.** `-n1` vs `-n3`; explicit `--dist`
   modes; single-file vs full-suite. The axis that changes the outcome tells you the
   class: data contention, infra contention, or scheduling.
2. **Prove the root cause with evidence** — the actual timeout line, the FK
   constraint error, the dead-letter message — *before* claiming fixed. Instrument
   via the channel that actually surfaces (assert on message fields / a metric, not
   a log line that never escapes the worker — see § 6).
3. **Confirm with multiple consecutive green runs, not one.** One pass never proves
   a concurrency fix; loop it (`pytest … ` ×N, or `--count` with `pytest-repeat`)
   and require *all* green. This is the [`adversarial-verification`](../../generic/adversarial-verification/SKILL.md)
   discipline applied to flakiness: try to *break* the fix, don't just watch it pass once.

## Checklist

- [ ] Each failure diagnosed as **data** contention or **infra** contention before fixing.
- [ ] Global seed holds reference data only; **zero tenant rows** — `create_tenant` mints the graph.
- [ ] Edge/denied start states are `create_tenant` **params**, not post-hoc DB writes.
- [ ] Sequences restarted at a random high offset after migrate + seed.
- [ ] Mock servers are concurrency-capable (`ThreadingHTTPServer` + a state lock).
- [ ] Shared-queue drains filter to **own** messages; foreign messages released, never deleted/held.
- [ ] Drain first-message timeout > queue visibility timeout.
- [ ] Fail-closed paths log the budget **and** publish to a monitored channel.
- [ ] Env-driven config is set **before** the settings cache builds (root conftest / `.env`).
- [ ] Dist mode chosen in `addopts`/CLI (not a late `pytest_configure` flip).
- [ ] Un-scopeable all-tenant sweeps run via the phased plugin in **one pass** (phase 0 parallel → barrier → phase N alone, `-p no:phasing`); the project injects a `{phase: reset_fn}` mapping (`config._phase_reset`), resets are mid-run-safe (`GREATEST` on any sequence), and the barrier uses collection-time expected counts + a brief filelock and **fails loud** on timeout.
- [ ] Payloads built from factory context; boundary Pydantic validation catches shape drift.
- [ ] Flaky fixes proven by isolating the variable + N consecutive green runs, with evidence.
