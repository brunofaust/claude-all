# Free-threaded Python 3.14 (`python3.14t`) — opt-in reference

> Reference page for the `brunofaust-python-style` skill. Opt-in guidance only: the skill's
> baseline stays Python 3.12+. A project adopts free-threading by choice, never by default.

## Status and baseline

- Free-threaded CPython (PEP 779, "supported but optional") ships in 3.14 as a separate
  interpreter build, `python3.14t`. The default `python3.14` build still has the GIL.
- **The project floor stays `requires-python = ">=3.12"`** until a project explicitly raises it.
  Free-threading is an *opt-in runtime*, not a language-version change. Do not raise
  `requires-python`, do not add 3.14-only syntax, and do not edit `pyproject-toml.md` or
  `installation.md` because of this reference.
- Free-threaded builds are not the same ABI as the default build. Extension modules must be
  built for the `cp314t` tag. A package that only ships `cp314` wheels will not import on `python3.14t`.

## When to use it

Use a free-threaded interpreter when **all** of these hold:

- The hot path is **CPU-bound pure-Python** work (parsing, transformation, scoring, math loops)
  that is already split across threads and is held back by the GIL.
- The work does **not** mainly sit inside C extensions that already release the GIL.
  Polars, DeltaTable and most blocking I/O already run in parallel on the default build
  because they release the GIL, so a free-threaded build gains little there.
- Every dependency on the hot path has a `cp314t` wheel or is pure Python (see the
  compatibility check below).

Do **not** use it for:

- I/O-bound async code. The event loop already handles it; the GIL is rarely the bottleneck.
- Services where a single dependency lacks `cp314t` wheels and cannot be replaced cheaply.
- Latency-sensitive single-threaded paths. They get slower on the free-threaded build (see cons).

For CPU-bound work that needs no shared mutable state, prefer `InterpreterPoolExecutor`
(see `async-patterns.md`) once the project floor is 3.14. Free-threading is for threads that
must share memory.

## Pros and cons

**Pros**

- Threads run Python bytecode in parallel. A CPU-bound pure-Python workload can scale with cores
  without the process overhead of `ProcessPoolExecutor`.
- Threads share memory, so no pickling of inputs or results.

**Cons and risks**

- **Single-threaded slowdown.** The free-threaded build pays for per-object locking and
  biased reference counting. Measure the real workload on both builds before switching.
- **C-extension risk.** An extension that is not thread-safe, or not marked as free-threaded
  compatible, can crash or corrupt data once the GIL is absent. A missing `cp314t` wheel is the
  easy case; a wheel that imports but is not thread-safe is the hard one.
- **Shared-state locking becomes your job.** Code that relied on the GIL for atomicity of
  `dict`/`list` operations, or for the order of side effects, now races. Every shared mutable
  structure needs an explicit lock or a single owner.
- **Silent re-enabling.** A dependency can import a non-free-threaded extension and re-enable
  the GIL at runtime. The process then behaves like the default build without any error.
- **Thread-offload owner rule still applies.** Free-threading does not change who owns thread
  creation. More parallel threads make an unbounded pool more dangerous, not less.

## How to implement it

### 1. Install the free-threaded interpreter with uv

```bash
uv python install 3.14t
uv venv --python 3.14t
uv sync --python 3.14t
```

Keep the project's dependency declaration unchanged. `uv` selects the free-threaded build only
for this environment; `requires-python` still reads `>=3.12`.

### 2. Keep one thread entry point

Thread offload stays owned by the single wrapper (`run_in_thread()` or the owned pool from
`async-patterns.md`). Do not add a second pool. Do not call `ThreadPoolExecutor` or
`asyncio.to_thread` directly in new code; the thread-subprocess guard blocks raw use.
An explicit exception needs a `# guard:allow` comment with a reason.

```python
import asyncio
from collections.abc import Sequence

from app.thread import run_in_thread  # the project's owner wrapper


def score_chunk(rows: Sequence[bytes]) -> int:
    """Pure-Python CPU-bound work; safe on free-threaded builds only if it owns its state."""
    return sum(len(row) for row in rows)


async def score_all(chunks: Sequence[Sequence[bytes]]) -> list[int]:
    """Fan out CPU-bound chunks through the owned pool; results come back in input order."""
    return list(
        await asyncio.gather(*(run_in_thread(score_chunk, chunk) for chunk in chunks))
    )
```

### 3. Size the pool from Settings

The worker count is configuration, not a constant. The owner module that builds the pool must
take its `max_workers` from the `Settings` model (see `config.md`), never from `os.cpu_count()`
at module level and never hardcoded. The `run_in_thread()` example in `async-patterns.md` shows
`max_workers=10` as a literal; when you adopt it, replace that literal with the setting below.

```python
from concurrent.futures import ThreadPoolExecutor  # guard:allow — the owner module is the only constructor

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration — thread pool sizing lives here."""

    model_config = {"extra": "forbid"}

    thread_pool_workers: int = 8


BLOCKING_THREADPOOL = ThreadPoolExecutor(
    max_workers=Settings().thread_pool_workers,
    thread_name_prefix="blocking-pool",
)
```

The default in the `Settings` class is the only place the number appears. Tune it per deployment
via the environment, and keep it bounded so free-threading cannot oversubscribe the host.

### 4. Never assume the GIL

Free-threaded code must not rely on the GIL for:

- **Atomicity.** `counter += 1` on a shared int is not atomic. Use a lock, or a `queue.Queue`
  owned by one thread.
- **Ordering.** Completion order of threads is arbitrary. Preserve order by index or by
  `run_in_thread` return values, not by append order.
- **Container safety.** Compound operations on a shared `dict`/`list` (check-then-set,
  read-modify-write) need a lock around the whole sequence.

```python
import threading

_totals_lock = threading.Lock()
_totals: dict[str, int] = {}


def add_total(key: str, amount: int) -> None:
    """Read-modify-write under one explicit lock; the GIL is not a substitute."""
    with _totals_lock:
        _totals[key] = _totals.get(key, 0) + amount
```

Prefer no shared state at all: have each chunk return its result, and combine the results on the
event loop. Use a lock only when sharing is unavoidable.

## How to check dependency compatibility (manual procedure)

This is a documented procedure, not a shipped checker. Run it by hand before adopting the
free-threaded build and again when a dependency is upgraded.

1. **Wheel availability per package.** For each direct and transitive dependency, confirm a
   `cp314t` wheel exists for each target platform (look for `cp314t` in the filename on the
   package index). A pure-Python package (`py3-none-any`) is compatible without a `cp314t` wheel.
   Any dependency with only `cp314` wheels is a blocker.
2. **Runtime GIL check.** On the free-threaded interpreter, with `PYTHON_GIL` unset (the default,
   so an incompatible extension is allowed to re-enable the GIL), confirm the GIL is off after all
   imports have run:

   ```python
   import sys

   assert not sys._is_gil_enabled(), "GIL was re-enabled by an imported extension"
   ```

   `sys._is_gil_enabled()` is a CPython private helper. Use it only in a manual check or a test
   guard, never in production logic.
3. **Test suite on the free-threaded interpreter.** Run the full suite under `python3.14t`:

   ```bash
   uv run --python 3.14t pytest
   ```

4. **Test suite with the GIL forced off.** Setting `PYTHON_GIL=0` keeps the GIL off even when an
   incompatible extension is imported. That hides the re-enable, so the run must turn the
   resulting `RuntimeWarning` into a failure:

   ```bash
   PYTHON_GIL=0 uv run --python 3.14t pytest -W error::RuntimeWarning
   ```

   Run this with the same pytest options as the normal suite, including any xdist worker count
   the project uses.
5. **Treat a re-enabled GIL as a finding.** If step 2 reports the GIL on, or step 4 fails with a
   `RuntimeWarning` about the GIL being re-enabled by an extension, the dependency that caused it
   is a blocker. Record the package
   name and version, and either pin a free-threaded-compatible release or keep the project on
   the default build for that deployment. Do not silence the assertion.
6. **Record the result.** Note the interpreter build, the dependency versions checked, and the
   test results in the pull request description.

## Testing guidance

- Run the thread-touching tests on both `python3.14` and `python3.14t` once the procedure above
  passes.
- Tests that assert ordering must assert on index or result position, never on the order threads
  finish.
- Keep leak checks (thread counts, pool shutdown) in the suite; free-threaded regressions often
  show up as leaked threads first.

## Summary rules

- 3.14t is opt-in. The project floor is `>=3.12` until a project explicitly raises it.
- Thread work goes through the one owned wrapper, sized from `Settings`.
- No implicit GIL assumptions: explicit locks or no shared state.
- Verify dependencies by hand (wheel tags, `sys._is_gil_enabled()`, the suite with and without
  `PYTHON_GIL=0`). A re-enabled GIL is a finding.
