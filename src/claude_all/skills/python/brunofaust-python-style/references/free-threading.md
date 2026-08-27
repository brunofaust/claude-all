# Free-threading (PEP 703) — the GIL-disabled build

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed
> summary; this file holds the full depth.

## What this covers

**PEP 703 — *free-threading* — is a build-time option at Python 3.14** that compiles the
interpreter without the Global Interpreter Lock (GIL). "Free-threaded" describes that
GIL-disabled runtime: multiple OS threads genuinely execute Python bytecode *in parallel*
instead of taking turns on one lock.

This file is about running the interpreter itself with no GIL. It is **not** about
`concurrent.futures.InterpreterPoolExecutor` (PEP 734) or subinterpreters — that tool has a
different mechanism (each interpreter *keeps* its own GIL, so they isolate rather than
parallel-share) and is already covered in
[`async-patterns.md`](async-patterns.md). Scope of this reference:

- When to adopt the free-threaded build vs. the default GIL build, and vs. subinterpreters.
- How to run code under it.
- How to check that your runtime and dependencies are actually free-thread capable.
- The safety implications — what the GIL was quietly doing for you and what stops now.

On the 3.14 baseline free-threading is **regular and supported** (it graduated out of the
experimental `--disable-gil` opt-in of 3.13), but it remains **opt-in per interpreter**: the
default interpreter is still GIL-enabled, and adopting it is a team-wide decision, not a
per-module import. One process, one build.

## When to use it

| Situation | Default choice |
| --------- | -------------- |
| Mostly I/O-bound async code | **Keep the default GIL build.** `asyncio` rarely needs multiple threads for I/O; the GIL is not your bottleneck. |
| CPU-bound **pure-Python** work on multiple threads that share the result set | **Free-threaded build** — the only way Python threads achieve true parallel execution; no pickling, no separate memory space. |
| CPU-bound work that does **not** need shared mutable state | `InterpreterPoolExecutor` (PEP 734) or `ProcessPoolExecutor` — isolation instead of sharing, no data-race tax. → `async-patterns.md` |
| CPU-bound **C extension** (Polars, NumPy, DeltaTable) | Those extensions already release the GIL / hand off to native threads — `run_in_thread()` (see `async-patterns.md`) is simpler and safer than going free-threaded. |
| Baking a brand-new, pure-Python CPU-bound service from scratch | **Consider free-threading from day one** — try-concurrency in tests, thread-safe from the start. Migrating later is real work. |

Rule of thumb: free-threading buys you parallel *Python-threaded* execution of *pure-Python*
compute. If your CPU work already runs in a C extension or is already isolated in a
subinterpreter/process, you gain little and inherit the data-race tax for nothing.

## Pros and cons

### Pros

1. **True parallelism for Python threads.** CPU-bound pure-Python code scales across cores;
   the GIL is no longer a serialization point.
2. **Shared-memory concurrency stays simple API-wise.** You keep `threading.Thread` /
   `run_in_thread()` / thread pools — no pickling, no fork/`ProcessPoolExecutor` IPC, no
   subinterpreter serialization of results. The threads share the process heap directly.
3. **No interpreter-marker wheel juggling for pure-Python deps** — packages without C
   extensions are identical across builds (see compatibility below).
4. **GIL contention disappears** for workloads that currently thrash it (many short-lived
   Python objects, heavy reference-count traffic, lock-hungry `cachebox`/dict hot loops).

### Cons

1. **A `t`-suffixed wheel for every C extension.** Any dependency with compiled native code
   must ship a free-threaded wheel — ABI tag `cp314t`, not `cp314`. Packages that do not yet
   publish one block the whole build.
2. **Memory and single-threaded overhead.** Free-threaded builds use per-object reference
   counting strategies that cost memory and that you pay even when running one thread; a
   single-threaded workload is often a few percent slower than the same code on the GIL build.
3. **The GIL was a de-facto safety net — it is gone.** Python's `list`/`dict`/`set` and
   reference counting were safe against concurrent mutation *because* only one thread ran at
   a time. Without the GIL, **two threads mutating one dict/list can crash or silently corrupt
   it.** Correctness now has to be *designed*, not inherited.
4. **Ecosystem maturity.** Support is uneven; the audit of "which of our wheels build `cp314t`"
   is a real project task, and a few native deps may be pinning old releases to stay
   compatible.
5. **Two build lines to maintain in CI** if some services go free-threaded and others do not
   (jobs, package cache keys, matrix entries).

## How to implement it

### 1. Run with a free-threaded interpreter

Free-threaded builds ship as a separate interpreter variant (the `t` marker / wheel tag). With
`uv` (the skill's dependency tool):

```bash
uv python install 3.14t     # install the free-threaded 3.14 build
uv run --python 3.14t python -c "import sys; print(sys._is_gil_enabled())"
# -> False
```

Match the project's chosen Python to the build: a free-threaded project declares
`requires-python = ">=3.14"` and pins its toolchain to a `t` build so every dev and the CI run
use the same runtime (mirroring the `prek` `language_version` pin discipline).

### 2. Verify at runtime — don't assume

```python
import sys
import sysconfig


def is_free_threaded() -> bool:
    """True when the running interpreter was built without the GIL (PEP 703)."""
    return bool(sysconfig.get_config_var("Py_GIL_DISABLED"))


def gil_enabled() -> bool:
    """True when the GIL is actually on in this interpreter."""
    return bool(sys._is_gil_enabled())
```

- `sysconfig.get_config_var("Py_GIL_DISABLED")` returns `1` on a free-threaded build.
- `sys._is_gil_enabled()` is the runtime answer and is the more direct check at run time
  (`sysconfig` reflects the build; `sys._is_gil_enabled()` reflects the running state).

Gate any code that genuinely needs to know at the boundary, and fail loudly on a build
mismatch ("this CPU-parallel path is only correct on the GIL-disabled build") rather than
letting it silently run single-threaded or unsafely.

### 3. Add a GIL-enabled regression test

A single test asserts the interpreter is the intended build, so a stray non-`t` Python in a
dev environment or CI doesn't silently weaken the guarantees. Mirror the naming/pattern of the
skill's `references/testing.md` conventions:

```python
def test_runs_free_threaded() -> None:
    """This suite must execute on the GIL-disabled build."""
    assert sys._is_gil_enabled() is False
```

### 4. Make shared mutable state safe

Whatever the `threading` code did on the GIL build now races. Before flipping the build:

- **Prefer immutable / copy-on-write data.** `Mapping`/`Sequence` (the skill's immutable
  parameter defaults) are the right instinct here too — pass copies, don't mutate shared
  `dict`/`list` from multiple threads.
- **Explicitly lock what must be shared and mutable** — `threading.RLock`, an `asyncio`
  `Lock` reached only from async, or a `cachebox` cache (internally mutex'd) — and don't rely
  on "the GIL will serialize it".
- **Run the full suite under the free-threaded build** (`pytest -n auto` AND a serial pass),
  not just the concurrency tests — latent races often surface in unrelated tests.

## How to check dependency compatibility

A pure-Python (no C extension) dependency behaves identically under the free-threaded build —
the same `.py` files run either way. Only packages with **compiled native code** differ, and
they must ship a free-threaded wheel. That is the entire audit.

### 1. Wheel ABI tags

Free-threaded wheels carry a `t`-suffixed ABI tag. For a 3.14 free-threaded build on x86-64
manylinux this looks like:

```
cp314t-cp314t-manylinux_2_17_x86_64
```

- `cp314t` (build tag and ABI tag both suffixed `t`) ⇒ free-threaded wheel — compatible.
- `abi3` / stable-ABI wheels (`abi3-cp314t` on free-threaded) ⇒ compatible by design; the
  stable ABI is independent of the GIL.
- plain `cp314` C-extension wheel ⇒ **the build it was compiled for has the GIL**; it will be
  skipped by a free-threaded runner (or fail at import) — native deps with only `cp314` wheels
  block adoption until their maintainers publish `cp314t`.

### 2. Audit your dependency tree

The cheapest screen is what a free-threaded `uv sync` pulls: if every compiled dependency
resolves a `cp314t` (or stable-ABI) wheel, the resolver is your audit. Skim for any fallback to
a `py3-none-any` (pure) wheel on a package that is secretly non-pure, and check `pip debug
--verbose` / `pip download --platform <free-threaded-tag>` for a project to see a target
wheel's effective ABI tags.

### 3. C extension audit criteria

A C extension *may* be free-thread-safe if it follows PEP 703's guidance. Your checklist when a
`cp314t` wheel exists but you can't assume correctness:

- **No global interpreter state without a lock** — singletons and module-level C caches are the
  usual data races in native code.
- **Reference counting still correct without the GIL** — extensions that hand-rolled refcounts
  were relying on the GIL's serialization; the build's leak/race checkers flag this.
- **Bindings built with GIL-aware tooling** — pybind11 (`py::gil_scoped_release`),
  Cython (`nogil` / legacy GIL handling), and `setuptools`-`free-threading` flags all change
  behavior between builds; "it compiled" is not "it's thread-safe".
- **The build, not the source, is what you trust** — import and stress it from a free-threaded
  interpreter with a threaded hammer before shipping.

### 4. The definitive check is the runtime

Nothing beats running your suite on the free-threaded build. CI should add a matrix job that:

1. installs with the `t` interpreter,
2. asserts `sys._is_gil_enabled() is False` (test in §Implement step 3),
3. runs unit + integration tests, then
4. runs a threaded stress of the parts you parallelize (see safety below).

## Security and data-integrity risks

Free-threading is a correctness and safety change, not just a speed knob:

1. **Data races on shared mutable state are now real.** On the GIL build, two threads mutating
   one `dict`/`list` were serialized; you could get away with sloppy sharing. Without the GIL,
   concurrent mutation can corrupt the structure — silent wrong data, crashes in `dict`/`list`
   internals, nondeterministic failures that pass locally and fail in prod. The fix is design
   (immutability, explicit locks), not "we tested it and it looked fine."
2. **One process, one shared heap.** The free-threaded build is still a single interpreter
process — all threads share memory. It has *none* of the isolation a subinterpreter or a
   subprocess provides. Isolation decisions that `ProcessPoolExecutor` gives you for free
   (a crash/poisoned state can't leak across the boundary) must now be made per-thread in code.
3. **No pickling/shared-memory escape hatch either way.** Free-threading shares the heap by
   design, so you skip `pickle` — but a data race is also not a pickling/versioning problem you
   can catch at a serialization boundary. The corruption happens in the live heap, invisibly,
   and only shows up later. This is why the test strategy must include the threaded stress and
   the `xdist` concurrency isolation checks the skill already enforces (`references/testing.md`).
4. **Confused/double execution on a corrupted result** — a data race on the counter/state that
   drives retries or idempotency (see `single_flight` in `async-patterns.md`) can make two
   threads believe the same critical section is free. Cross-process primitives like a DynamoDB
   conditional `PutItem` remain the authority; don't replace them with "it's free-threaded now,
   so my thread-local check is safe."
5. **Environment surface.** Free-threaded and GIL builds are different runtimes. A subtle
   behavior difference between dev (GIL build) and prod (free-threaded) is a class of bug that
   only bites under load — pin the build everywhere including `prek`/CI, exactly like the
   `language_version` pin the skill mandates.

**Bottom line:** adopt free-threading for a *measured* pure-Python CPU-parallel bottleneck,
with the build pinned across environments, a `cp314t`-wheel audit of every C dependency, a
GIL-enabled regression test, and a threaded stress pass. If the code needs shared mutable
state, reach for immutable types and explicit locks — the GIL no longer provides the cover it
once did.
