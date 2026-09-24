# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces a free-threaded build option (PEP 703) that removes the Global Interpreter Lock (GIL) to allow true parallel execution of Python bytecode across multiple OS threads. The free-threaded interpreter is a separate build configuration; it is **not** the default.

Free-threading interacts with the skill’s async-first conventions:

- `async/await` + `run_in_thread()` remains the default for blocking I/O and C-extension work.
- `concurrent.futures.InterpreterPoolExecutor` (PEP 734, available in Python 3.14+) provides true parallelism for CPU-bound *pure Python* work in a free-threaded build.
- `asyncio.to_thread` and `ThreadPoolExecutor` for CPU-bound work are banned by `banned-api` rules; use `run_in_thread()` for blocking seams and `InterpreterPoolExecutor` for CPU-bound pure Python.

## When to Use

Use the free-threaded interpreter when **all** of the following hold:

- Workload is CPU-bound and written in pure Python (no heavy C extensions).
- Tasks are independent; no shared mutable state is required between workers.
- Arguments and results are picklable (or limited to shareable primitive types).
- The runtime is Python 3.14+ free-threaded build and the dependency tree is verified compatible.

Do **not** use free-threading for:

- Blocking I/O — use async + `run_in_thread()` for file/network calls.
- C-extension-heavy workloads like Polars, DeltaTable, NumPy — these already release the GIL effectively; `run_in_thread()` is the correct seam per `async-patterns.md`.
- Code that relies on shared mutable globals, caches, or in-process singleton state. Free-threading exposes data races rather than fixing them.

Typical fit:

- Pure Python parsing, math, text processing, JSON transformations.
- CPU-bound batch processing where each item is self-contained.
- Work that would otherwise require `ProcessPoolExecutor` but where process startup overhead is undesirable.

## Pros and Cons

### Pros

- True parallelism for pure Python bytecode without process isolation overhead.
- Lower memory and startup cost than `ProcessPoolExecutor`.
- Same API surface as `ThreadPoolExecutor` / `InterpreterPoolExecutor` — easy migration for compatible code.
- Works well with `asyncio` orchestration: offload CPU work to an `InterpreterPoolExecutor` from async code via `run_in_thread()`.

### Cons

- Requires a free-threaded Python 3.14+ build (`cp314t` ABI). AWS Lambda does not currently ship a free-threaded runtime; use ECS/VM workloads.
- C extensions must be free-threaded safe. Many extensions still assume GIL semantics; they may crash or corrupt state.
- No shared mutable state. Interpreter isolation means objects are not shared between interpreters except via pickling of a limited set of types.
- Pickling constraints: only picklable arguments/results are supported. Non-picklable objects (open files, sockets, DB connections) cannot cross interpreter boundaries.
- Ecosystem maturity: wheel availability for `cp314t` is growing but not universal. CI must gate on compatibility.
- Debugging and race conditions become more likely if code was previously “safe” only because the GIL serialized access.

## Implementation

### Verify the interpreter

```python
import sys
import sysconfig

def is_free_threaded() -> bool:
    # Python 3.14+ flag
    return getattr(sys.flags, "freethreading", False)

def is_free_threaded_build() -> bool:
    # Config var set in free-threaded builds
    return sysconfig.get_config_var("Py_GIL_DISABLED") == 1
```

Add a startup check for services that require free-threading:

```python
if not is_free_threaded():
    raise RuntimeError("This service requires a free-threaded Python 3.14+ build")
```

### InterpreterPoolExecutor pattern

For CPU-bound pure Python, use `InterpreterPoolExecutor`. This is the Skill-approved replacement for `ProcessPoolExecutor` in free-threaded builds.

```python
from concurrent.futures import InterpreterPoolExecutor

def compute_square(x: int) -> int:
    return x * x

with InterpreterPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(compute_square, range(100)))
```

Hybrid CPU + I/O workload:

```python
import asyncio
from concurrent.futures import InterpreterPoolExecutor

async def process_batch(items):
    # Offload CPU work to subinterpreters
    with InterpreterPoolExecutor() as executor:
        loop = asyncio.get_running_loop()
        # run_in_thread is the Skill seam for blocking calls
        results = await asyncio.to_thread(
            lambda: list(executor.map(pure_python_work, items))
        )
    return results
```

Important constraints:

- Only picklable arguments/results. Shareable types without pickling are limited to `str | bytes | int | float | bool | None | tuple | memoryview`.
- Avoid C extensions that hold global state.
- Do **not** share DB clients, HTTP sessions, or caches across interpreters.

Interaction with Skill conventions:

- Prefer `run_in_thread()` for blocking C extensions (Polars, DeltaTable, file I/O) per `async-patterns.md`.
- Use `InterpreterPoolExecutor` for CPU-bound pure Python.
- Never use `asyncio.to_thread` directly; it is banned by `banned-api` — use `run_in_thread()`.

## Dependency Compatibility

Free-threading shifts compatibility from “works under GIL” to “works without GIL”. Check dependencies before adoption.

### Interpreter and wheel checks

- Confirm the Python build is free-threaded: `sys.flags.freethreading` is `True`.
- Inspect wheel tags: free-threaded wheels use ABI tag `cp314t`. `pip list` and `pip show` should show `cp314t` builds where available.
- In CI, add a gate:

```python
# tests/test_free_threading.py
def test_free_threaded_interpreter():
    import sys
    assert getattr(sys.flags, "freethreading", False), "Requires free-threaded Python"
```

### C-extension audit

1. List direct dependencies with C extensions: `pipdeptree` + filter for `*.so` packages.
2. Check for known incompatible patterns:
   - Extensions using `Py_BEGIN_CRITICAL_SECTION` incorrectly.
   - Libraries that rely on global mutable state.
   - Packages that wrap C libraries with non-thread-safe APIs.
3. Prefer pure-Python implementations where possible.
4. Test with a small parallel workload and run under ThreadSanitizer / helgrind if available.

### Runtime verification

- Run a smoke test that spawns `InterpreterPoolExecutor` with a CPU-bound function to confirm parallelism.
- Monitor for crashes, deadlocks, or data corruption under load.
- Add a `prek.toml` CI gate for free-threaded builds:

```toml
[[tools.prek.hooks]]
id = "free-thread-check"
name = "Verify free-threaded interpreter"
entry = "python -c \"import sys; assert getattr(sys.flags,'freethreading',False)\""
language = "system"
```

### Compatibility strategies

- Keep a GIL build CI job alongside free-threaded for comparison.
- Pin dependencies to `cp314t` wheels when available; avoid source builds that pull in incompatible C code.
- Isolate incompatible libraries behind `run_in_thread()` — they run in the same interpreter but benefit from GIL release for C code.
- Document exceptions: libraries that are known incompatible remain on `run_in_thread()` or process isolation.

## Related Documentation

- See `references/async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines.
- Refer to `references/enforcement.md` for banned-api rules regarding threading mechanisms.
- Consult `SKILL.md` for high-level skill conventions and recommendations.
