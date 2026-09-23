# Python 3.14 Free-Threading — Reference Guide

This reference covers Python 3.14 free-threaded execution (PEP 703, Python 3.14+), when to use it, pros and cons, implementation patterns, and dependency compatibility checks.

## Overview

Python 3.14 introduces free-threaded build options that remove the Global Interpreter Lock (GIL) for true parallel execution of Python bytecode. This enables `concurrent.futures.InterpreterPoolExecutor` (PEP 734) to run CPU-bound pure-Python workloads in parallel across multiple interpreters.

Key points:
- Free-threading is a build configuration; runtime support is available in Python 3.14+.
- Existing CPython code benefits automatically where GIL was the bottleneck, but shared mutable state must be avoided across interpreters.
- The skill baseline is Python 3.14+ with strict typing, asyncio-first, and `InterpreterPoolExecutor` for CPU-bound pure Python.

## When to use

Use free-threaded execution / `InterpreterPoolExecutor` when:
- CPU-bound pure-Python work that is embarrassingly parallel and pickle-able.
- No shared mutable state between tasks; inputs and outputs are serializable.
- You need true parallelism beyond asyncio concurrency.

Do NOT use for:
- I/O-bound work → use asyncio + `run_in_thread()`.
- CPU-bound C extensions → they already release GIL effectively; use `run_in_thread()`.
- Code relying on global mutable state, module-level caches, or non-pickleable objects.

## Pros and cons

Pros:
- True parallelism for CPython bytecode without rewriting to C.
- Better utilization of multi-core CPUs for pure-Python hot loops.
- Interpreter isolation reduces accidental cross-task contamination.

Cons:
- No shared memory between interpreters; only picklable data transfers.
- Higher overhead per task due to interpreter startup and pickling.
- Not all third-party packages are free-thread safe or compatible.
- Debugging and profiling become more complex across interpreters.

## Implementation

### Basic usage

```python
from concurrent.futures import InterpreterPoolExecutor
import asyncio

def cpu_bound(n: int) -> int:
    total = 0
    for i in range(n):
        total += i * i
    return total

async def main():
    loop = asyncio.get_running_loop()
    with InterpreterPoolExecutor(max_workers=4) as pool:
        tasks = [loop.run_in_executor(pool, cpu_bound, 10_000_000) for _ in range(4)]
        results = await asyncio.gather(*tasks)
    return results
```

### Hybrid CPU + I/O

Combine with asyncio for I/O:
```python
from concurrent.futures import InterpreterPoolExecutor
from myapp.core.thread_pool import run_in_thread

async def process_items(items):
    # CPU phase in separate interpreters
    with InterpreterPoolExecutor() as pool:
        cpu_results = await asyncio.gather(*[
            asyncio.to_thread(pool.submit, transform, item) for item in items
        ])
    # I/O phase using run_in_thread
    results = await asyncio.gather(*[run_in_thread(fetch, r) for r in cpu_results])
    return results
```

Rules:
- Inputs/outputs must be pickleable.
- Avoid global state; pass dependencies explicitly.
- Prefer `InterpreterPoolExecutor` for CPU-bound pure Python; prefer `run_in_thread()` for blocking I/O or C extensions.

## Dependency compatibility

Check compatibility before adopting free-threading:

1. Python version: requires Python 3.14+ free-threaded build.
2. Third-party packages:
   - Verify package is free-thread safe; avoid C extensions with global state.
   - Test with `PYTHON_GIL=0` or free-threaded interpreter.
   - Use `pip-audit` and review changelog for free-threading support.
3. Internal code:
   - Audit for shared mutable globals, module-level caches, or `threading.Local` usage.
   - Ensure all data passed between interpreters is pickleable.
   - Run tests under free-threaded interpreter with `-n auto`.

Compatibility checklist:
- [ ] Python 3.14+ free-threaded build installed
- [ ] Dependencies verified free-thread safe
- [ ] No global mutable state in CPU paths
- [ ] Inputs/outputs are pickleable
- [ ] Tests pass under free-threaded interpreter

## Related documentation

- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
- Consult `SKILL.md` for high-level skill conventions and recommendations
