# Free-threaded Python 3.14 (3.14t) — opt-in reference

**Scope.** The project baseline stays **Python 3.12+** (`requires-python = ">=3.12"`). Free-threading is an
**opt-in** build: a 3.14t interpreter gets true parallel threads, and every code path must also run on a
standard 3.12 interpreter with the GIL. Nothing in this reference raises the floor.

Free-threaded CPython (PEP 779, supported in 3.14) is a separate build that drops the Global Interpreter
Lock. Its interpreter binary is named `python3.14t`, and its wheels carry the `cp314t` ABI tag.

---

## (a) When to use it

**Use the free-threaded build when all of these hold:**

- The hot path is **pure Python CPU work** (parsing, scoring, transforms, simulation loops) that today is
  split across threads and gets no speed-up because the GIL serialises it.
- The work is **shareable**: inputs are immutable or copied, and any shared mutable state can be guarded
  by an explicit lock.
- Profiling shows the bottleneck is CPU, not the network or disk.

**Do NOT use it for:**

- **I/O-bound async work.** HTTP, AWS SDK calls, database queries, and queue polling already run on the
  event loop (`aiobotocore`, async DB drivers). Threads add nothing there. Keep it on the loop.
- **Work that is already parallel in C.** Polars `.collect()`, DeltaTable, and other C/Rust extensions
  release the GIL during heavy work. They already scale with `run_in_thread()` on 3.12. Free-threading
  mostly helps the Python glue around them.
- **Code that needs isolation between workers.** Use a process boundary, not shared threads.
- **Short, latency-sensitive single calls.** Single-threaded speed on 3.14t is lower than on the GIL build,
  so a single request does not get faster.

**Decision rule:** if you cannot name the CPU-bound pure-Python loop and show it runs in parallel threads
today, stay on the default build.

---

## (b) Pros and cons

| Aspect | Free-threaded 3.14t | Default GIL build (3.12 baseline) |
| --- | --- | --- |
| Parallelism for pure-Python CPU work | Threads run in parallel on multiple cores | Threads take turns; no CPU speed-up |
| Single-thread speed | Measurably slower in current releases (measure your own workload) | Reference speed |
| Memory | Higher per-object overhead | Lower |
| C-extension support | Only extensions built for `cp314t` run without re-enabling the GIL | All `cp3xx` wheels work |
| Library ecosystem | Each dependency needs a `cp314t` wheel or a source build that is free-thread safe | Mature |
| Code that relied on GIL atomicity | **Breaks silently** (races on `dict`/`list` compound updates, lazy init, counters) | Works by accident |
| Runtime behaviour | If an incompatible extension is imported, CPython **re-enables the GIL** for the process with a warning | N/A |
| Debugging | Races are harder to reproduce | Simpler |

**Cons to weigh first:** the single-thread slowdown hits every request, while the parallel gain only
appears in the CPU-bound hot path. Verify a gain with a benchmark before adopting.

---

## (c) How to implement

### Rule 1 — keep the owner wrapper as the only thread entry point

All blocking work still goes through the single owner `run_in_thread()` (see
[`async-patterns.md`](async-patterns.md) → *Running Blocking Code in Threads*). Do **not** call `threading`,
`ThreadPoolExecutor`, or `asyncio.to_thread` from application code: the thread-subprocess guard blocks
`ThreadPoolExecutor` and `asyncio.to_thread`. Raw `threading` is not matched by the guard, but the single-owner
rule still forbids it in application code, and the owner module is the one place that sizes and names the pool.

The owner module is the one place that knows whether the interpreter is free-threaded. Application code
calls `run_in_thread()` and does not branch on the build.

### Rule 2 — detect the build at runtime, in the owner module only

```python
import sys
import sysconfig
from typing import Final


def is_free_threaded_build() -> bool:
    """True when this interpreter was compiled without the GIL (3.14t)."""
    return bool(sysconfig.get_config_var("Py_GIL_DISABLED"))


def is_gil_enabled() -> bool:
    """True when the GIL is active right now (3.13+ API; always True on 3.12)."""
    probe = getattr(sys, "_is_gil_enabled", None)
    return True if probe is None else bool(probe())


FREE_THREADED: Final[bool] = is_free_threaded_build() and not is_gil_enabled()
```

- `Py_GIL_DISABLED` tells you the **build** is free-threaded.
- `sys._is_gil_enabled()` tells you whether the GIL is **active at runtime**. A 3.14t process can still
  have the GIL on, for example after an incompatible extension is imported or with `PYTHON_GIL=1`. Use
  both checks; the build flag alone is not enough.
- Read the flag once at import time in the owner module. Do not read environment variables here; the
  pool size and any override come from `Settings`.

### Rule 3 — keep a 3.12 fallback path

On 3.12 the same wrapper runs the same code. Threads still work; they just do not run Python bytecode in
parallel. Write call sites so that **correctness does not depend on the build**. Parallel speed-up is a
property of the owner's pool size, not of the call site. Call sites keep calling `run_in_thread()` unchanged
on both builds; only the owner's configured worker count differs.

If a CPU-bound job needs more parallelism than the owner's thread pool can give on 3.12, move that job to a
process boundary owned by the same module. Do not add a second thread pool.

### Rule 4 — size the pool from Settings

Never hard-code the worker count (see [`config.md`](config.md)):

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="forbid")

    # The one owner pool. On 3.14t size for the CPU cores the CPU-bound work can use;
    # on the GIL build a larger pool only adds context switching.
    blocking_max_workers: int = 8


SETTINGS = Settings()
```

Recommended sizing (set per deployment, verify with a benchmark):

- **3.14t, CPU-bound pure Python:** raise `blocking_max_workers` toward the usable cores for that task, with
  headroom for the event loop and other services.
- **Any build, I/O-bound or C-extension-bound:** keep the existing `blocking_max_workers` value.
- **3.12 fallback:** keep `blocking_max_workers` modest; threads will not add CPU throughput.

### Rule 5 — GIL rules (apply on both builds, enforce on 3.14t)

1. **No reliance on GIL atomicity.** Do not assume `d[k] += 1`, `list.append` plus a check, lazy
   `if x is None: x = build()`, or "check then set" is safe. On 3.14t each of these is a race.
2. **Explicit locks around shared mutable state.** Any `dict`, `list`, `set`, counter, or object attribute
   touched by more than one thread is guarded by a `threading.Lock` owned by the same class, or is
   replaced by an immutable value passed between threads. Keep the lock next to the state it protects.
   (The lock object is an allowed implementation detail inside the owner class; application modules
   still do not import `threading` for thread creation.)
3. **Pass immutable inputs.** Send `Mapping`/`Sequence`/frozen Pydantic models to workers, and return new
   values. Never let two workers mutate one Polars frame or one Pydantic model in place.
4. **Thread-safety check for caches and clients.** Before a cache (`cachebox`, see
   [`caching.md`](caching.md)) or an SDK client object is shared across threads:
   - confirm the library documents thread safety for its type (cache objects and client sessions often do
     not guarantee it for concurrent writes);
   - if not, wrap access in the owner class with a lock, or give each worker its own instance;
   - a cache keyed by tenant still follows the tenant-isolation rules; threads do not change the keying.
5. **No `threading.local` as a shared store.** It is per-thread, not per-process, and hides state from
   the owner.
6. **Test under real concurrency.** A race test runs many workers against the same owner and asserts the
   final state. Run it under `python3.14t`; a single-threaded test cannot expose these bugs.

---

## (d) Dependency compatibility check (generic procedure)

This procedure has no per-library status table: a library's free-threading status changes by release, and
it must be verified against the **resolved** lock for the project, not copied from a document.

1. **Wheel tags on the resolved lock.** `uv.lock` records the filename of every wheel it pins. For each
   package with a compiled extension, the lock must contain a `cp314t` wheel for each target platform. A
   pure-Python wheel (`none-any`) is compatible by construction. A package with no recorded wheels (sdist
   only) needs a source build against `python3.14t`, which must be verified in CI. Run this check against
   the project's lock (it reads only the lock, no network):

   ```python
   # tmp/cp314t_check.py — run with: python3.14 tmp/cp314t_check.py
   import tomllib
   from pathlib import Path

   lock = tomllib.loads(Path("uv.lock").read_text())
   for pkg in lock["package"]:
       urls = [w["url"].rsplit("/", 1)[-1] for w in pkg.get("wheels", [])]
       if not urls:
           print(f"{pkg['name']} {pkg.get('version', '?')}: no wheels recorded (sdist only)")
       elif not all("-none-any" in u for u in urls) and not any("cp314t" in u for u in urls):
           print(f"{pkg['name']} {pkg.get('version', '?')}: compiled wheels but no cp314t")
   ```

   Every line printed is a blocker or a CI source-build item for the free-threaded path. Record the result
   in the project, not in this skill. A lock lists only the platforms it was resolved for, so repeat the
   check for each target platform's lock.

2. **Install and run the suite under the free-threaded interpreter.** Create an environment on
   `python3.14t` and run the full test suite there:

   ```bash
   uv python install 3.14t
   uv venv --python 3.14t .venv-314t
   uv sync --locked --python 3.14t
   uv run --python 3.14t pytest -n auto
   ```

   A test that passes on the GIL build and fails on 3.14t points to a race or a missing `cp314t` wheel.
   Investigate it before any other change.

3. **Confirm at runtime that the GIL is disabled.** Add a startup or test assertion, run under 3.14t, and
   check it passes:

   ```python
   import sys


   def test_gil_disabled_in_free_threaded_run() -> None:
       """Only meaningful on a 3.14t run; the check is skipped on the GIL build."""
       import sysconfig
       import pytest

       if not sysconfig.get_config_var("Py_GIL_DISABLED"):
           pytest.skip("requires a free-threaded (3.14t) interpreter")
       assert sys._is_gil_enabled() is False
   ```

   If the GIL re-enables, an extension in the import graph is not free-thread safe. The process still runs
   correctly but gets no parallel speed-up. Find the module that re-enabled it (run with
   `PYTHON_GIL=0` to force the GIL off and surface the failing import) and treat it as a blocker for
   the free-threaded path.

4. **Gate the adoption.** Free-threading stays an opt-in deployment target until steps 1–3 pass on the
   resolved lock and a benchmark shows a real gain for the CPU-bound path. The baseline in `pyproject.toml`
   and `prek.toml` is unchanged by this procedure.

---

## Quick rules (free-threading)

- ❌ Raw `threading`, `ThreadPoolExecutor`, or `asyncio.to_thread` in application code — use `run_in_thread()`.
- ❌ Assuming GIL atomicity for compound updates or lazy initialisation.
- ❌ Shared mutable state without an explicit lock owned next to the state.
- ❌ Hard-coded worker counts — size from `Settings`.
- ❌ Declaring 3.14t support without a `cp314t` wheel check and a full suite run under `python3.14t`.
- ❌ Raising `requires-python` to 3.14 for free-threading alone — it is an opt-in target.
