# Free-threaded Python 3.14 (no GIL) — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a
> condensed summary; this file holds the full depth.

Free-threaded (aka *no-GIL*) Python is a build/interpreter variant where the
Global Interpreter Lock is disabled, so threads within a **single process** can
run Python bytecode on multiple cores at the same time. On the CPython 3.14
baseline this is selectable at runtime, so you can opt a process in or out
without a separate interpreter build.

This page is the **when / why / how / prove-it** reference. It deliberately does
**not** re-derive the async concurrency patterns (`TaskGroup`, semaphores,
`run_in_thread`) — those live in [`async-patterns.md`](async-patterns.md) and
apply regardless of the GIL. The relationship to
`concurrent.futures.InterpreterPoolExecutor` is drawn out at the bottom because
people conflate the two and they are solving different problems.

## What free-threaded actually is

- **A build-time / runtime property of the interpreter.** On 3.13 it was the
  experimental `--disable-gil` build flag. On 3.14 the GIL can be toggled at
  runtime: `-X gil=0` (and the `PYTHON_GIL=0` env var) disables it for that
  process; `-X gil=1` keeps it on. The default build on 3.14 ships with the GIL
  enabled unless the distribution builds free-threaded.
- **Threads run Python in parallel.** With the GIL off, two Python threads can
  evaluate bytecode on two cores concurrently. The GIL only ever made *one*
  thread run Python at a time, so plain-thread CPU-bound code could never beat a
  single core under the GIL.
- **It is opt-in per process.** You don't rebuild your code. You choose the
  interpreter bytes you run your code under and whether to disable the GIL at
  launch. Your code must still be *thread-safe*, which the async-first style here
  mostly already is (no module-level mutable state — see
  [`visibility.md`](visibility.md)).

### Detecting whether the running interpreter is free-threaded

```python
import sys


def is_free_threaded() -> bool:
    """True if the running interpreter has no GIL.

    ``sys._is_gil_enabled()`` is available on the 3.13+ baseline and returns
    False exactly when the free-threaded build is active with the GIL off.

    Returns:
        Whether a GIL protects this process's interpreter.
    """
    return hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled()


def require_free_threaded() -> None:
    """Fail fast if the process was not launched without a GIL.

    Raises:
        RuntimeError: if the GIL is enabled.
    """
    if not is_free_threaded():
        raise RuntimeError(
            "free-threaded operation required — launch with `-X gil=0` "
            "or a free-threaded build"
        )
```

`sys._is_gil_enabled()` is the concrete check for "is the GIL currently on".
When the GIL is off, `sys._is_free_threaded()` reports the build is the
free-threaded variant (private/underscore — assert it in code only as a runtime
probe, never in public APIs). Key this decision into your `Settings` as a flag,
not hardcoded per call site.

## When to use it (and when NOT to)

### Use free-threaded when

1. **You have real CPU-bound work that threads should parallelise.** Pure-Python
   loops, parsing, hashing, validation — code whose hot path runs bytecode, not a
   C extension that already releases the GIL.
2. **Your workers already run on threads** (`run_in_thread`, a long-lived
   `ThreadPoolExecutor`) and you want them to actually scale across cores without
   migrating to subinterpreters or processes.
3. **Your dependencies are free-threaded-compatible** (see the compatibility
   section below) — the wheel set, not just pure-Python libs.

### Do NOT use it when

1. **Your hot path is a C extension that already releases the GIL** (Polars,
   DeltaTable, orjson, cryptography) — the GIL was never your bottleneck there;
   free-threading adds correctness risk for zero throughput gain.
2. **The work doesn't parallelise or you have fewer cores than threads** — a
   single-threaded process gains nothing from a GIL-free interpreter.
3. **Any dependency lacks a free-threaded wheel or isn't thread-safe** (see
   dependency compatibility). This is the disqualifier that stops most projects in
   practice.
4. **You need GIL-protected C extensions that use global/static state** — those
   can corrupt each other without the GIL serialising them.

### Decision table

| Situation | Free-threaded? | Rationale |
| --- | --- | --- |
| CPU-bound pure-Python parser on many threads | ✅ Yes | threads finally scale across cores |
| CPU-bound Rust/C extension (Polars, orjson) | ❌ No | already releases the GIL; no gain, added risk |
| Blocking I/O offloaded to threads | ❌ No | I/O-bound; GIL is idle anyway |
| One process, few threads, single core | ❌ No | nothing to parallelise |
| Interpreter needs to run multiple unrelated CPU jobs | ❌ Prefer `InterpreterPoolExecutor` | see boundary below |

List dropped dependencies — the moment a required wheel has no
free-threaded build, the decision is made *for* you.

## Pros

- **True parallelism for pure-Python threads.** ThreadPool-based work can reach
  N cores without `ProcessPool`-style pickling or IPC.
- **Shared memory, no serialisation.** Threads still share objects directly — no
  `InterpreterPoolExecutor` value restriction, no `ProcessPool` pickling cost.
- **Async-layering stays the same.** `asyncio` + `uvloop` + `TaskGroup` code
  needs no structural change; the concurrency patterns in
  [`async-patterns.md`](async-patterns.md) work identically.
- **Granular opt-in.** `-X gil=0` per process — your library can ship one codebase
  that runs under either mode, guarded by a startup probe.

## Cons

- **The whole dependency must be thread-safe.** Without the GIL, data races in a
  C extension are real concurrency bugs, not masked slowness. A thread-unsafe
  extension can crash or corrupt silently.
- **Wheel availability is the gate.** A binary dependency without a
  free-threaded wheel (ABI tag `t`, e.g. `cp314t`) can't be installed into a
  free-threaded build; some projects don't ship one yet.
- **Shared-mutable-state foot-guns get real.** Global caches, lazy-init singletons
  and `lru_cache`-style state assume GIL-atomicity. The async-first / no-module-
  global-mutable-state discipline of this skill is exactly what keeps you safe
  here.
- **Smaller ecosystem/test surface.** Builds and CI matrixes expand, and some
  tools (profilers, some debuggers) assume a GIL.

## How to implement it

1. **Get a free-threaded interpreter.** Use a 3.14 distribution built
   free-threaded (e.g. `uv python install cpython-3.14t`, `pyenv install
   3.14t`), or a default build and disable the GIL at runtime with `-X gil=0`.
2. **Pick the process, not the package.** Free-threading is a runtime decision.
   Opt the *process* in (env var / launch flag), guard entry points, and keep
   `Settings` carrying a `free_threaded: bool` derived from the runtime probe so
   CI and prod launch consistently.
3. **Audit every dependency for a free-threaded wheel** (section below) before
   flipping the flag.
4. **Run the async-first rules as your thread-safety contract.** The discipline
   already fights the failure modes: inject dependencies (never `mod._client =
   mock`), hold no module-global mutable state, scope caches and tenant-bound
   state per-invocation (see [`tenant-isolation.md`](tenant-isolation.md) and
   [`visibility.md`](visibility.md)).
5. **Add a test that runs the CPU-bound path on threads** and asserts the result
   is deterministic (e.g. under `pytest` on a free-threaded interpreter), plus a
   CI job that launches with `-X gil=0` so the free-threaded mode is covered.

```python
# Launch a free-threaded process:
#   uv run --python cpython-3.14t -X gil=0 python -m myapp
PYTHON_GIL=0 uvicorn myapp.main:app
```

## Dependency compatibility — prove it, don't assume

Compatibility is the deciding factor, so it gets concrete, runnable checks — not
a vague checklist. Run these against the exact interpreter you'll deploy.

### 1. Confirm the interpreter is actually free-threaded

```python
import sys

if hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled():
    print("free-threaded (no GIL)")
else:
    print("GIL enabled — not running free-threaded")
```

### 2. Scan installed distributions for free-threaded wheels

In a free-threaded environment, every installed wheel must carry the `t` ABI tag
for its C extensions (`cp314t`, not `cp314`) or be pure-Python. Enumerate what
you have and flag binaries built for the GIL interpreter:

```python
import sysconfig
from importlib.metadata import distributions

# Free-threaded builds expose a distinct extension suffix and platform tag.
print(sysconfig.get_platform())          # e.g. linux-x86_64 (native)
# A free-threaded build adds the 't' variant to extension module suffixes:
# e.g. cpython-314t-x86_64-linux-gnu.so
import _imp
print(_imp.extension_suffixes())
```

For each binary wheel, confirm its tag matches the free-threaded build. The
**`t` suffix on the ABI tag** (`cp314t`) is the machine-readable signal that the
wheel was built for the no-GIL build; a plain `cp314` C-extension wheel won't
load correctly.

### 3. Inspect C extensions for GIL dependence

Even a wheel that installs can be thread-unsafe. Two checks:

- **Prefer free-threaded wheels** (tagged `t`). Only these are built and tested
  against the no-GIL / atomic-refcount runtime.
- **For source builds or mixed extensions**, look for global/static mutable state
  or reliance on `PyGILState`-style assumptions — without the GIL, static C globals
  are a data race. Projects with `Py_LIMITED_API` extensions need the free-threaded
  build to internalise the `PyMutex` / atomic-refcount requirements.

### 4. Metadata + pip scanning (including transitive deps)

Don't audit only your direct list — the whole tree must resolve. This snippet
surfaces the installable set and lets you grep for any binary distribution
lacking the `t` tag:

```sh
# Show ABI tags each distribution provides (the `-t` column is the free-threaded one):
pip index versions --python 3.14   # not enough — use the pinned tree
python -m pip list --format=freeze
```

Then for a *chosen* interpreter, resolve the full tree to free-threaded wheels:

```sh
uv lock --python 3.14t              # uv resolves against the free-threaded ABI tag set
uv sync --python 3.14t
```

If `uv sync` (or `pip install`) fails to find a wheel for any pinned version, that
dependency has no free-threaded wheel — the blocker is concrete, not debated.

### 5. Dependency-supply-chain check (pip-audit)

Keep the usual audit gate in the matrix:

```sh
pip-audit --python $(python -c "import sysconfig; print(sysconfig.get_config_var('PYTHON_CONFIG'))")
# or simply, against a free-threaded venv:
pip-audit
```

`pip-audit` runs against whatever environment you invoke it in — run it in the
free-threaded venv so the advisories reflect that interpreter's resolution.

### 6. Automated CI validation

Make the compatibility check a gate, not a one-time manual pass:

```yaml
# Free-threaded wheel + run gate
steps:
  - run: uv sync --python 3.14t
  - run: uv run --python 3.14t python -c "import sys; assert hasattr(sys,'_is_gil_enabled') and not sys._is_gil_enabled()"
  - run: uv run --python 3.14t pip-audit
  - run: uv run --python 3.14t pytest -n auto -X gil=0
```

**In plain terms:** the *minimum* automated admission test is (a) the env is
actually free-threaded (`sys._is_gil_enabled()` false), (b) the full dependency
tree resolved to free-threaded wheels (`uv sync --python 3.14t` succeeds), and
(c) the suite passes under `-X gil=0` under concurrency.

## Relationship to `InterpreterPoolExecutor` — the boundary

Both free-threading and
[`concurrent.futures.InterpreterPoolExecutor`](async-patterns.md) (PEP 734) are
a "get more parallelism out of 3.14" story, but they solve different problems and
are **not** interchangeable:

| | Free-threaded (no GIL) | `InterpreterPoolExecutor` (PEP 734) |
| --- | --- | --- |
| Parallelism unit | threads in ONE interpreter | separate subinterpreters |
| Share state directly | ✅ yes — threads share objects | ❌ no — only picklable / shareable types cross |
| Overhead of handoff | low (shared memory) | low-ish (no process fork, but isolated) |
| C-extension requirement | every dep must be thread-safe + `t`-wheel | interpreter-isolated; extensions still must support subinterpreters |
| Best for | many CPU-bound *threads* sharing state | unrelated CPU-bound jobs that don't share mutable state |

**Decision rule:** if the parallel work must share mutable state across units,
only free-threading *or* threads gives you that — subinterpreters isolate it away,
so `InterpreterPoolExecutor` is wrong there. If the jobs are independent CPU-bound
units, `InterpreterPoolExecutor` gives parallelism with **isolation** and without
requiring thread-safe extensions — which is usually the safer default. Free-threading
is the aggressor choice you take deliberately when you *need shared mutable state
across parallel threads* and you own the full dependency's thread-safety.

The async-patterns reference is authoritative for when to pick
`InterpreterPoolExecutor` vs `run_in_thread`; this page only sets the boundary:
**free-threading is a property of the interpreter you're already in;**
`InterpreterPoolExecutor` is a way to *escape* that interpreter into isolated ones.

## FAQ

- **Does free-threading fix the async event loop?** No — the event loop was never
  GIL-bound in the way blocking handlers are. `uvloop` + `run_in_thread` from
  [`async-patterns.md`](async-patterns.md) are the async answers; free-threading
  only makes the *threads you already offload to* run faster on CPU-bound code.
- **Is it "just turn off the GIL"?** No — it changes the runtime contract for every
  C extension and any code that relied on GIL-atomicity for thread safety. It is
  a dependency-compatibility decision first.
