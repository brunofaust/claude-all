# Free-threaded Python 3.14 — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

Python 3.14 ships an officially supported **free-threaded build** (PEP 779) in which the
Global Interpreter Lock (GIL) is disabled. Threads then run Python bytecode in parallel
on multiple cores inside one interpreter. This is an **opt-in build**, not a change to
the language: the same source runs on the regular (GIL) build and on the free-threaded
build (`python3.14t`).

Free-threading is **not** part of the 3.12 baseline. Adopt it only when the project's
floor is 3.14 and the dependency check in [Dependency compatibility](#dependency-compatibility)
passes.

## Overview

| Concept | What it means |
| --- | --- |
| GIL build (default) | One thread executes Python bytecode at a time. Threads still help for I/O and for C code that releases the GIL. |
| Free-threaded build (`3.14t`) | No GIL. Threads run Python bytecode in parallel. Objects are protected by per-object locks and biased reference counting instead. |
| Subinterpreters (PEP 734, `InterpreterPoolExecutor`) | Each interpreter has its own GIL, so CPU work runs in parallel without free-threading. Data crosses the boundary by pickling. See [`async-patterns.md`](async-patterns.md). |

Free-threading and subinterpreters are alternative routes to CPU parallelism. They are
not the same feature and they do not replace each other.

## When to use

Use the free-threaded build when **all** of these hold:

- The work is **CPU-bound pure Python** (parsing, transformation, scoring, math loops)
  and profiling shows the event loop or a thread pool is saturated by it.
- The work needs to **share in-process state** (a large in-memory structure, a warm cache
  owned by the process) that would be expensive or impossible to pickle into a subprocess
  or subinterpreter.
- Every dependency on the hot path has a `cp314t` wheel or is pure Python (see the checklist).
- The team can make the shared mutable state **thread-safe by construction** (see below).

Do **not** use it for:

- **I/O-bound work.** `await` on aiobotocore / httpx / asyncpg already overlaps I/O. Free-threading
  adds nothing there.
- **C extensions that already release the GIL** (Polars, DuckDB, orjson on large payloads).
  They already run in parallel under `run_in_thread()`.
- **Short tasks** (< 1 ms). Thread start-up and synchronization overhead dominates.
- **Production services that cannot yet install a 3.14t wheel set.** Stay on the GIL build.

Decision table:

| Situation | Use |
| --- | --- |
| I/O-bound (network, S3, DB) | `async` + native async client — no threads needed |
| Blocking I/O or C extension that releases the GIL | `run_in_thread()` on the GIL build |
| CPU-bound pure Python, share large in-process state, all deps 3.14t-ready | Free-threaded build + owned thread pool |
| CPU-bound pure Python, isolated inputs/outputs, picklable | `InterpreterPoolExecutor` (PEP 734) |
| CPU-bound, one-off, short | Leave it on the event loop or skip the parallelism |

## Pros and cons

### Pros

- **Real parallelism for pure Python** in one process: no pickling of inputs and outputs,
  and no copy of large in-memory structures per worker.
- **Shared memory is cheap.** A read-mostly lookup table is loaded once and read from all threads.
- **Simpler mental model than multiprocessing** for code that already uses `threading` correctly.
- **Lower memory** than N worker processes each importing the same packages.

### Cons

- **Shared mutable state becomes a real race.** Code that was "accidentally safe" under the GIL
  (e.g. `counter += 1` on a shared dict) can now corrupt data or lose updates.
- **Some C extensions are not ready.** A missing `cp314t` wheel means the extension is either
  rebuilt from source or the import fails. Extensions that rely on the GIL for their own safety
  may crash or misbehave.
- **Single-thread overhead.** The free-threaded build is slower on single-threaded code than
  the GIL build; the gain appears only with real parallel load.
- **Harder to debug.** Races are timing-dependent and rarely reproduce in unit tests.
- **Not in the 3.12 baseline.** Adopting it raises the project's Python floor and the CI matrix.
- **Ecosystem still maturing.** Verify behaviour and performance for each workload before adoption.

## Implementation

### 1. Install a free-threaded interpreter

```bash
# uv names the free-threaded variant with a "t" suffix
uv python install 3.14t
uv venv --python 3.14t .venv-ft
uv run --python 3.14t python -c "import sys; print(sys._is_gil_enabled())"
# False on the free-threaded build (unless the GIL was re-enabled, see below)
```

In `pyproject.toml`, pin the floor and keep the GIL build as the default for everything
that is not CPU-bound:

```toml
[project]
requires-python = ">=3.14"
```

Declare the free-threaded requirement in CI as a separate job (`python-version: "3.14t"`),
not as a silent assumption on the developer machine.

### 2. Detect the build and the GIL state at runtime

```python
import sys
import sysconfig


def is_free_threaded_build() -> bool:
    """Build flag set by CPython when compiled with --disable-gil."""
    return bool(sysconfig.get_config_var("Py_GIL_DISABLED"))


def is_gil_enabled() -> bool:
    """True when the GIL is active in this process (always True on the GIL build)."""
    return sys._is_gil_enabled()  # noqa: SLF001 — documented 3.13+ introspection hook
```

Use these only for startup logging and diagnostics. Do not branch business logic on them;
the code must be correct on both builds.

Note that `sys._is_gil_enabled()` is a private-looking name but is the documented
introspection function for this feature. If the project's visibility rule rejects it, wrap
it once in the settings/diagnostics module and import the wrapper.

### 3. Force the GIL on or off (only for diagnosis)

```bash
PYTHON_GIL=1 uv run --python 3.14t python -m myapp   # re-enable the GIL
PYTHON_GIL=0 uv run --python 3.14t python -m myapp   # keep it off
python3.14t -X gil=0 -m myapp                         # equivalent command-line form
```

Use `PYTHON_GIL=1` to bisect a problem: if a crash or race disappears, the bug is a
thread-safety issue, not a build issue. Do not ship a service that depends on `PYTHON_GIL=1`
without an explicit decision recorded in the project docs.

### 4. Offload CPU-bound pure Python to an owned thread pool

In production code, thread offload goes through the project's single owner of the
thread-offload seam (`run_in_thread()`, see [`async-patterns.md`](async-patterns.md)). The
example below uses `ThreadPoolExecutor` directly only to show the mechanism.

```python
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor


def score_record(record: str) -> int:
    """CPU-bound pure Python. Must not mutate shared state."""
    return sum(ord(ch) for ch in record)


def score_all(records: Sequence[str], workers: int) -> list[int]:
    """Parallel map over immutable inputs; results come back in input order."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(score_record, records))
```

Inside `async def`, call the sync function through the owned offload seam so the event
loop stays free:

```python
import asyncio


async def score_all_async(records: Sequence[str], workers: int) -> list[int]:
    """Async wrapper; the thread pool does the CPU work off the event loop."""
    return await asyncio.to_thread(score_all, records, workers)  # illustrative only
```

In the project, replace the `asyncio.to_thread` line with `run_in_thread(...)`. Raw
`asyncio.to_thread` is blocked by the `banned-api` rule in [`enforcement.md`](enforcement.md).

### 5. Hybrid workload: CPU work plus I/O

Keep I/O on the event loop and send only the CPU stage to threads. Use a `TaskGroup` so one
failure cancels the rest:

```python
import asyncio
from collections.abc import Sequence


async def process_batch(records: Sequence[str], workers: int) -> list[int]:
    """Fetch-then-compute: I/O stays async, CPU fans out to threads."""
    async with asyncio.TaskGroup() as tg:
        tasks = [
            tg.create_task(asyncio.to_thread(score_record, record))  # illustrative only
            for record in records
        ]
    return [task.result() for task in tasks]
```

Pattern rules:

- Fetch all I/O first (or inside the coroutine that owns the request), then hand the pure
  function an **immutable snapshot** (`Sequence`, frozen Pydantic model, tuple).
- Never let a worker thread `await` or touch the event loop directly.
- Bound the fan-out with a semaphore or the pool size from `Settings`. Never create an
  unbounded number of threads.

### 6. Make shared state thread-safe by construction

Rules, in order of preference:

1. **Immutable data.** Pass frozen Pydantic models, tuples, `Mapping` views. No mutation.
2. **Per-task results.** Each task returns a value; the caller merges. No shared accumulator.
3. **Owned, locked structure.** When sharing is unavoidable, wrap it in one class that holds a
   `threading.Lock` (or `RLock`) and exposes intent-named methods. Do not expose the raw dict.
4. **Atomic primitives** only where the standard library documents them as thread-safe
   (e.g. `queue.Queue`). Do not assume `dict` operations compose safely.

```python
import threading
from collections.abc import Mapping


class HitCounter:
    """Process-wide counter; all access goes through one lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}

    def increment(self, key: str) -> None:
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + 1

    def snapshot(self) -> Mapping[str, int]:
        with self._lock:
            return dict(self._counts)
```

Do not use `TypedDict` or `cast` for these structures (banned by the skill); use Pydantic models
at the boundary.

### 7. Test on the free-threaded build

- Add a CI job that runs the test suite on `3.14t`, with the GIL both on (`PYTHON_GIL=1`)
  and off (default).
- Run the concurrency-sensitive tests repeatedly (for example under `pytest-xdist` with
  `-n auto` and a loop) to surface races. A single green run proves nothing.
- Keep tests self-contained: no shared module-level state between tests, as required by the
  testing reference.

## Dependency compatibility

Every package imported by a free-threaded process must be safe without the GIL. Check each
dependency in this order.

### Step 1 — Pure Python or compiled?

```bash
uv pip show <package>            # look at the "Location" and whether it has .so/.pyd files
```

- **Pure Python** packages are safe for the free-threaded build if they hold no
  unsynchronized global state. Still review them for module-level mutable caches.
- **Compiled** packages need a `cp314t` wheel (see step 2) or must be built from source
  against the free-threaded headers.

### Step 2 — Is there a free-threaded wheel?

Free-threaded wheels carry the ABI tag `cp314t`. Check the index before installing:

```bash
# Fails with "No matching distribution" when no cp314t binary wheel exists for the platform
pip download <package> --only-binary=:all: --no-deps \
  --python-version 3.14 --abi cp314t --platform manylinux_2_28_x86_64 -d /tmp/ft-wheels
```

The download is a probe only: delete `/tmp/ft-wheels` afterwards. Run it per platform you ship to.

Or inspect a specific release page on PyPI and look for a file ending in `-cp314-cp314t-*.whl`.

A package that ships only `cp314-cp314-*.whl` (the GIL ABI) is **not** free-threaded
compatible, even if it installs. It will re-enable the GIL at import time or be refused.

### Step 3 — Does importing it re-enable the GIL?

Run a minimal import under the free-threaded build and check:

```bash
uv run --python 3.14t python -c "import sys, <package>; print(sys._is_gil_enabled())"
```

If this prints `True` while `PYTHON_GIL` is unset, the import has re-enabled the GIL. Treat
that package as incompatible for the free-threaded path, or isolate it to the GIL build.

### Step 4 — Full dependency sweep

```bash
uv run --python 3.14t python - <<'PY'
import importlib.metadata as md
import sys

print("gil_enabled:", sys._is_gil_enabled())
for dist in sorted(md.distributions(), key=lambda d: d.metadata["Name"].lower()):
    print(dist.metadata["Name"], dist.version)
PY
```

Record the result in the project's dependency notes with one line per package:
`name version — pure | cp314t wheel | GIL re-enabled on import | blocked`.

### Step 5 — Strategy for incompatible packages

| Finding | Strategy |
| --- | --- |
| Pure Python, no mutable globals | Use on the free-threaded build |
| Compiled, `cp314t` wheel exists | Use on the free-threaded build; pin the version |
| Compiled, no `cp314t` wheel | Keep the GIL build for that workload, or move the call to a subprocess / `InterpreterPoolExecutor` |
| Re-enables the GIL on import | Same as above; do not depend on `PYTHON_GIL=1` in production |
| Unknown thread-safety | Wrap all calls in one owned class with a lock (rule 3 above), or keep it off the hot path |

Maintain the decision in the project docs, not in code comments. Revisit the table on each
dependency upgrade.

## Checklist before adopting

- [ ] Project floor is 3.14 and CI has a `3.14t` job
- [ ] Workload is CPU-bound pure Python and profiling shows it
- [ ] Every hot-path dependency has a `cp314t` wheel or is pure Python, and the sweep is recorded
- [ ] Shared mutable state is removed or owned by one locked class
- [ ] No reliance on `PYTHON_GIL=1` in production
- [ ] Concurrency tests run repeatedly on `3.14t`
- [ ] Fallback to the GIL build is documented
