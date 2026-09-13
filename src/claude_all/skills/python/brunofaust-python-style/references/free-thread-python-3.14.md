# Free-threaded Python 3.14 — Reference

> Reference page for the `brunofaust-python-style` skill. Covers the Python 3.14 free-threaded build and the `InterpreterPoolExecutor` shipped with 3.14.

## Overview

Python 3.14 ships two concurrency-related advancements that are relevant to this skill:

* **Free-threaded build** — The CPython build with the Global Interpreter Lock disabled, enabled via PEP 703. Threads can execute Python bytecode in parallel. C extensions must be GIL-aware / release the GIL to benefit.
* **`concurrent.futures.InterpreterPoolExecutor`** — PEP 734, added in Python 3.14. Provides a pool of subinterpreters, each with its own GIL. Gives true parallelism for CPU-bound pure-Python work with a `ThreadPoolExecutor`-like API.

Both are opt-in. The baseline runtime for the skill is Python 3.14+, but the free-threaded build is not the default distribution.

### Relation to existing patterns

This skill already standardises:

* `run_in_thread()` for offloading blocking C extensions and I/O
* `InterpreterPoolExecutor` for CPU-bound pure-Python work
* `asyncio.TaskGroup` + `Semaphore` for structured async concurrency

Free-threading changes *when* threads are useful for Python bytecode; it does not replace `run_in_thread()` for blocking C extensions, which already release the GIL.

## When to use

Use the free-threaded build / interpreter pool when:

* **CPU-bound pure-Python workloads** with no shared mutable state: parsing, JSON, pure-Python math, data transformations without C extensions.
* **Throughput-bound services** that spawn many Python threads and want parallel bytecode execution without a process pool.
* **Hybrid workloads** where part of the pipeline is CPU-bound pure-Python and part is blocking I/O/C-extensions. Use free-threading for the pure-Python part and `run_in_thread()` for the blocking part.

Do *not* use free-threading for:

* Code that relies on global mutable state, module-level singletons, or non-thread-safe libraries. Each thread sees the same interpreter state.
* CPU-bound work that uses C extensions which *hold* the GIL for the entire operation. In that case `run_in_thread()` is the correct offload.
* Code that needs isolation and picklable handoffs. Prefer `InterpreterPoolExecutor` for isolation.

## Pros and Cons

### Pros

* **True parallelism for Python bytecode** in threads without spawning processes.
* **Lower memory overhead** than `ProcessPoolExecutor`; interpreters share read-only code objects.
* **Simpler deployment** than multiprocessing — no IPC serialization for shared libraries.
* **Works with existing threading APIs** — `threading.Thread`, `concurrent.futures.ThreadPoolExecutor` become parallel.

### Cons

* **Dependency compatibility** — many C/Rust extensions assume the GIL is present and may race or crash.
* **Global state is shared** — unlike subinterpreters, free-threading does not isolate memory. Race conditions become likely.
* **Pickling limitations** do not apply to threading, but shared mutable objects become a hazard.
* **Build availability** — free-threaded wheels are not universal; CI/CD must install the correct build.
* **Debugging complexity** — data races in Python code are harder to reason about than in a GIL-protected process.

Comparison with `InterpreterPoolExecutor`:

| Situation | Free-threaded threads | InterpreterPoolExecutor |
|-----------|----------------------|--------------------------|
| CPU-bound pure Python | Good parallelism, shared memory | True parallelism, isolated memory |
| Shared mutable state needed | Requires locks | Not possible across interpreters |
| C extensions that release GIL | Benefits from free-threading | May not work reliably |
| Picklable args/results required | No pickling needed | Pickling required |
| Overhead | Low | Higher due to interpreter start + pickling |

## Implementation

### Detecting free-threaded build

```python
import sys

def is_free_threaded() -> bool:
    # Python 3.13+ free-threaded builds expose this flag
    return getattr(sys, "_is_gil_enabled", lambda: True)() is False

print(is_free_threaded())
```

Also check the interpreter configuration at startup and fail fast if the expected build is missing.

### Basic pure-Python parallel work with InterpreterPoolExecutor

```python
from concurrent.futures import InterpreterPoolExecutor

def compute_square(x: int) -> int:
    return x * x

def run_batch(items: list[int]) -> list[int]:
    with InterpreterPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(compute_square, items))
    return results
```

*Arguments and results must be picklable.* Use only `str | bytes | int | float | bool | None | tuple | memoryview` for shared types where possible.

### C-extension offload — continue using run_in_thread

Free-threading does not replace `run_in_thread()` for blocking C extensions.

```python
import polars as pl
from pathlib import Path

# Polars releases the GIL; offload to thread pool to avoid blocking event loop
df = await run_in_thread(pl.read_parquet, "s3://bucket/data.parquet")
```

Do not call `asyncio.to_thread` directly; project policy requires `run_in_thread()`.

### Hybrid CPU + I/O example

```python
from concurrent.futures import InterpreterPoolExecutor
import asyncio

async def process_dataset(paths: list[str]) -> list[dict]:
    # I/O-bound read in threads
    async def read_one(path: str) -> bytes:
        return await run_in_thread(Path(path).read_bytes)

    raw = await asyncio.gather(*[read_one(p) for p in paths])

    # CPU-bound pure-Python parsing in subinterpreters
    def parse(data: bytes) -> dict:
        # pure-Python parsing, no C extensions
        return {"size": len(data)}

    with InterpreterPoolExecutor() as pool:
        parsed = list(pool.map(parse, raw))
    return parsed
```

Guideline: keep I/O and C-extension work in `run_in_thread()`, keep CPU-bound pure-Python work in `InterpreterPoolExecutor`. Avoid mixing shared mutable state between the two.

## Compatibility

### Dependency categories to assess

* **Pure-Python packages** — generally safe for free-threading, but check for global mutable state and non-thread-safe third-party code.
* **C extensions** — must be built for free-threaded CPython and release the GIL where appropriate. Extensions that hold the GIL for long periods negate benefits.
* **Rust extensions** — PyO3-based extensions need explicit free-threaded support; check for `gil-unsafe` annotations and official free-threaded wheels.
* **Third-party libraries** — validate that the library documents free-threaded support. Common offenders: NumPy, pandas, oracles with C backends.
* **Internal modules** — audit for module-level caches, mutable singletons, and assumptions about GIL-protected critical sections.

### Compatibility checks

1. **Build check**

   ```bash
   python -c "import sys; print(sys._is_gil_enabled() if hasattr(sys, '_is_gil_enabled') else 'unknown')"
   ```
   CI must run tests on both GIL and free-threaded builds.

2. **Picklability check for InterpreterPoolExecutor**

   Run a dummy pool with representative function and arguments:

   ```python
   from concurrent.futures import InterpreterPoolExecutor
   def identity(x): return x
   with InterpreterPoolExecutor(max_workers=2) as ex:
       assert ex.submit(identity, {"a": 1}).result() == {"a": 1}
   ```

3. **GIL release verification**

   For C extensions, confirm the library releases the GIL during hot paths. Benchmark parallelism: if throughput does not scale with threads, the extension is likely GIL-bound.

4. **Runtime race tests**

   * Execute a dummy interpreter pool with a picklable function that exercises the dependency.
   * Run the test suite under `ThreadPoolExecutor` with many threads on a free-threaded build to surface data races.
   * Use a stress test that repeatedly creates/destroys interpreters.

5. **Dependency matrix**

   Maintain a table per dependency:

   | Package | Type | Free-threaded wheel | GIL releases | Notes |
   |---------|------|---------------------|--------------|-------|
   | `polars` | C/Rust | Yes/No | Partial | Use `run_in_thread` |
   | `my-pure-lib` | Pure Python | N/A | N/A | Safe with locks |

### Compatibility strategies

* **Isolate incompatible libraries** behind `run_in_thread()` and keep them on the GIL build.
* **Pin free-threaded wheels** in `pyproject.toml` and CI.
* **Add runtime guard** that fails fast if a required free-threaded wheel is missing.
* **Document assumptions** in module docstrings: whether a function is safe for free-threading or requires InterpreterPoolExecutor isolation.

### Integration with project conventions

* Continue using `run_in_thread()` for blocking code. Free-threading does not remove this requirement.
* `InterpreterPoolExecutor` is the preferred parallelism mechanism for CPU-bound pure-Python work in Python 3.14+.
* Never use `asyncio.to_thread` or raw `ThreadPoolExecutor`; the banned-api hooks enforce this.
* Follow `enforcement.md` for threading and concurrency rules.

## Related documentation

* `references/async-patterns.md` — `run_in_thread`, `InterpreterPoolExecutor`, structured concurrency
* `references/type-hints.md` — picklable type constraints
* `SKILL.md` — high-level skill conventions
