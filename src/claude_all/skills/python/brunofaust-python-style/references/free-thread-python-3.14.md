# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces free-threaded execution (PEP 703) as an opt-in interpreter mode that removes the Global Interpreter Lock (GIL) per interpreter. When enabled, multiple OS threads can execute Python bytecode concurrently within the same process.

The skill's baseline targets Python 3.14 (`target-version = "py314"` in Ruff, `python_version = "3.14"` in mypy). Free-threading is not the default interpreter mode — it must be explicitly enabled at runtime (`PYTHON_FREE_THREADS=1`) and is supported on CPython builds compiled with `--disable-gil` or via the `free-threaded` distribution.

The primary standard library mechanism for parallel CPU-bound work in the Python 3.14+ ecosystem in this skill is `concurrent.futures.InterpreterPoolExecutor` (PEP 734). This creates multiple sub-interpreters, each with its own GIL-free execution context, allowing true parallelism for pure-Python CPU workloads without data races that arise from shared mutable state across interpreters.

Use `InterpreterPoolExecutor` for CPU-bound pure-Python tasks that are picklable. Use the skill's `run_in_thread()` wrapper (see `async-patterns.md`) for blocking I/O and C extensions, which already release the GIL effectively.

## When to use

Use free-threaded mode / `InterpreterPoolExecutor` when:

- **CPU-bound pure-Python workloads** that can be isolated per task. Examples: numerical transformations implemented in pure Python, parsing/compilation pipelines, heavy string processing, JSON schema validation loops.
- **Parallelism is measurably needed** and the workload is not already accelerated by C extensions that release the GIL (e.g., NumPy, PyPy, etc.).
- **Tasks are independent** and pass data via picklable arguments/results rather than shared mutable objects.

Do NOT use free-threading for:

- **Shared mutable state** across threads/interpreters. Objects must be picklable; mutable globals, shared caches, or in-process singletons will not be consistently visible.
- **Code that relies on CPython's memory model or CPython-specific thread-safety guarantees**. The skill's `external-system-ownership.md` patterns still apply — each external system has a single owner module.
- **I/O-bound work**: use `async/await` plus the skill's `run_in_thread()` wrapper. Free-threading adds interpreter start-up and pickling overhead for no benefit.
- **Blocking C extensions** that are already GIL-releasing. `run_in_thread()` is preferred; `InterpreterPoolExecutor` is unnecessary.

The rule of thumb from `async-patterns.md`: `InterpreterPoolExecutor` for CPU-bound pure Python; `run_in_thread()` for blocking I/O and C extensions.

## Pros and cons

**Pros**

- True parallelism for CPU-bound pure-Python code within a single process, without needing multiprocessing and its heavier IPC.
- Lower memory overhead compared to multiprocessing for many short-lived workers.
- Works well with the skill's existing `async/await` conventions: CPU work can be off-loaded to an `InterpreterPoolExecutor` and awaited in an async context, keeping the event loop responsive.
- Aligns with Python 3.14 as the skill baseline; tooling (Ruff, mypy) already targets `py314`.

**Cons**

- No shared mutable state across interpreters. Arguments and results must be picklable; objects with open sockets, DB connections, or file handles cannot cross interpreter boundaries.
- Pickling overhead. Large data structures serialize/deserialize on each call. For small grainsize tasks, overhead can dominate.
- Third-party compatibility. Libraries that use C extensions with non-free-threaded builds, or that rely on thread-local state, may not work correctly under free-threading.
- Debugging complexity. Stack traces span interpreters, and some profilers/ debuggers do not yet fully support free-threaded builds.
- Not a panacea for concurrency: I/O still benefits more from async than from free-threading.

**Decision guidance**

Prefer `InterpreterPoolExecutor` when the task is pure-Python and CPU-bound. Prefer `run_in_thread()` when the task is blocking I/O or uses a GIL-releasing C extension. Never mix shared mutable state with either approach; follow the skill's data-modeling and external-system-ownership rules.

## How to implement

Free-threading is enabled at interpreter start:

```bash
PYTHON_FREE_THREADS=1 python -m myapp
```

or build/activate a free-threaded CPython distribution.

### Basic pattern: `InterpreterPoolExecutor` for CPU-bound pure Python

```python
from concurrent.futures import InterpreterPoolExecutor
import orjson

def heavy_transform(payload: bytes) -> bytes:
    # pure Python work, no shared state
    data = orjson.loads(payload)
    # ... CPU-intensive pure Python transformations ...
    return orjson.dumps(data)

async def process_batch(items: list[bytes]) -> list[bytes]:
    # Run CPU work in parallel interpreters
    with InterpreterPoolExecutor(max_workers=4) as pool:
        # map is picklable; results are pickled back
        results = list(pool.map(heavy_transform, items))
    return results
```

Guidelines:

- The callable and its arguments must be picklable.
- Do not pass open connections, thread-locals, or mutable globals.
- Keep grainsize reasonable; too small → pickling overhead dominates.
- Use the skill's `thread_pool` for thread-based work; use `InterpreterPoolExecutor` only for CPU-bound pure Python.

### Hybrid pattern: CPU + I/O

```python
from concurrent.futures import InterpreterPoolExecutor
from myapp.core.thread_pool import run_in_thread

async def fetch_and_process(url: str) -> bytes:
    # I/O in a thread (GIL-releasing)
    raw = await run_in_thread(fetch_http, url)

    # CPU pure-Python in a separate interpreter
    with InterpreterPoolExecutor(max_workers=1) as pool:
        processed = pool.submit(heavy_transform, raw).result()
    return processed
```

This separates concerns: I/O via `run_in_thread()`, CPU via `InterpreterPoolExecutor`. Do not attempt to share a DB session or HTTP client across interpreters.

### Configuration in `pyproject.toml`

The skill already targets Python 3.14:

```toml
[tool.ruff]
target-version = "py314"
...
[tool.mypy]
python_version = "3.14"
```

No additional configuration is required to use `InterpreterPoolExecutor`; it is part of the standard library.

## Checking dependency compatibility

Free-threaded Python is sensitive to how libraries implement concurrency and memory management.

### Checklist

1. **Python runtime**
   - Verify you are running CPython 3.14+ built with free-threading enabled (`sys.implementation._multi_interp` or `PYTHON_FREE_THREADS` active).
   - `python -c "import sys; print(sys.version)"` should report 3.14+.

2. **Pure-Python libraries**
   - Generally safe. Ensure the library does not depend on global mutable state or thread-local storage.
   - Test parallelism under load to detect race conditions or pickling failures.

3. **C extensions**
   - Prefer libraries with free-threaded builds or those that explicitly release the GIL during compute.
   - Libraries that keep internal global state or assume GIL-protected critical sections may crash or corrupt data.
   - The skill's banned-API rules (`asyncio.to_thread`, `concurrent.futures`) centralize threading via `myapp.core.thread_pool`. Do not introduce new thread-pool usage without reviewing compatibility.

4. **Third-party packages**
   - Check the package's changelog / documentation for free-threading support or known issues.
   - Test integration in a staging environment with `PYTHON_FREE_THREADS=1`.

5. **Internal modules**
   - Audit for shared mutable singletons, `threading.local`, and direct use of `asyncio.to_thread` or `ThreadPoolExecutor`. These are banned outside their owner modules (`myapp.core.thread_pool`).
   - Follow `enforcement.md` banned-API rules; owner modules are explicitly whitelisted.
   - Ensure serialization uses `orjson` (skill preferred library) and not stdlib `json` except at designated serde boundaries.

6. **Picklability**
   - Use `copyreg` or custom reducers only where necessary. Avoid passing unpicklable objects (open files, sockets, DB connections) to `InterpreterPoolExecutor`.
   - Validate by running unit tests under the free-threaded interpreter.

### Strategies

- Start with isolated CPU-bound services. Move a pure-Python batch processor to `InterpreterPoolExecutor` first, validate correctness and performance.
- Keep I/O and CPU boundaries explicit. Use `run_in_thread()` for blocking I/O, `InterpreterPoolExecutor` for CPU.
- Monitor for pickling errors and serialization overhead. Profile with real payloads.
- When in doubt, prefer `run_in_thread()` for C extensions; reserve `InterpreterPoolExecutor` for pure-Python CPU work where parallelism is proven beneficial.

## Related documentation

- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
- Consult `SKILL.md` for high-level skill conventions and recommendations
