# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces free-threaded builds (PEP 703, also known as "no-GIL" builds).

* When `sys.flags.freethreading` is True, the interpreter allows multiple Python threads to execute bytecode concurrently without the Global Interpreter Lock (GIL).
* Free-threading is opt-in via the interpreter build and does not change the Python language semantics. Existing code continues to run, but thread-safety guarantees change.
* This feature is related to but distinct from `concurrent.futures.InterpreterPoolExecutor` (PEP 734, subinterpreters). Subinterpreters provide true parallelism per-interpreter with isolation; free-threading allows parallelism within a single interpreter.

The skill baseline is Python 3.14+. Free-threading is an advanced concurrency option for CPU-bound pure-Python workloads where the GIL was previously a bottleneck.

## When to Use

| Situation | Recommendation |
| --- | --- |
| CPU-bound pure Python (parsing, math, data transformations) where the GIL is the bottleneck and the codebase is free of shared mutable state | Evaluate free-threading. Start with a compatibility audit and limited roll-out. |
| CPU-bound C extensions (Polars, NumPy, PyArrow) | Free-threading offers little benefit — these extensions already release the GIL. Use `run_in_thread()` for offloading. |
| I/O-bound async workloads | Use `async/await` with `run_in_thread()` for blocking calls. Free-threading does not replace async. |
| Code with shared mutable globals, in-process caches, ORM sessions, or third-party libraries that assume GIL-thread-safety | Do not enable free-threading. The code will require refactoring. |
| Multi-process / subinterpreter workloads | Prefer `InterpreterPoolExecutor` for CPU-bound pure-Python work with picklable arguments/results. |

Guideline: Free-threading shines for CPU-bound pure-Python tasks that are already thread-safe by design (no shared mutable state, immutable data flow, pure functions). If your codebase relies on mutable shared state, stick with `InterpreterPoolExecutor` or `run_in_thread()`.

## Pros and Cons

### Pros
* True parallelism for pure-Python CPU-bound work without process overhead.
* Lower memory footprint than multi-process approaches.
* Compatible with existing `threading` code once thread-safety is ensured.
* Allows higher CPU utilization on multi-core machines for pure-Python tasks.

### Cons
* Breaks code that relies on GIL for implicit thread-safety. Shared mutable state becomes a race condition.
* C extensions may not be compatible or may have performance regressions. Many extensions use global state or non-thread-safe data structures.
* Pickling limitations remain for `InterpreterPoolExecutor`; free-threading does not remove them.
* Third-party library ecosystem support is still maturing. Wheels may not be built for free-threaded ABI (`cp314t`).
* Debugging concurrency bugs is harder — race conditions become visible only under load.
* AWS Lambda does not ship free-threaded runtimes. Use for ECS/VM workloads only.

## Implementation

### Interpreter Verification

Verify the running interpreter is free-threaded:

```python
import sys
print(sys.flags.freethreading)  # True if free-threaded
```

Also check `sysconfig` for ABI tags:

```python
import sysconfig
print(sysconfig.get_config_var('Py_GIL_DISABLED'))  # 1 if free-threaded
```

### pyproject.toml Pinning

Pin the interpreter in `pyproject.toml` and CI:

```toml
[project]
requires-python = ">=3.14"
```

For `uv`, ensure the project uses a free-threaded 3.14 interpreter:

```bash
uv python install 3.14
uv run --python 3.14 ...
```

Add a CI gate to verify free-threading:

```toml
# prek.toml
[[hooks]]
id = free-thread-check
name = free-thread-check
entry = python -c "import sys; assert sys.flags.freethreading, 'Not free-threaded'"
language = system
files = ''
```

### Hybrid Async + Free-Threading

Combine with async patterns:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=8)

async def process(items):
    loop = asyncio.get_running_loop()
    # Free-threaded interpreter allows true parallelism in thread pool
    results = await asyncio.gather(
        *(loop.run_in_executor(executor, cpu_bound_func, item) for item in items)
    )
    return results
```

### Avoiding Shared State

* Prefer immutable data structures and pure functions.
* Avoid module-level mutable globals.
* Use thread-local storage instead of shared caches.
* Audit third-party libraries for thread-safety.

## Dependency Compatibility

### Checks

1. **Interpreter verification via `sys.flags.freethreading` / `sysconfig`**
   - Run at start-up and in CI.

2. **Wheel ABI `cp314t` inspection**
   - Free-threaded wheels use ABI tag `cp314t` (t = thread-free).
   - Inspect installed wheels:
     ```bash
     python -c "import sys; print(sys.abiflags)"
     pip list | grep -E "cp314t"
     ```

3. **C-extension checklist**
   - Review dependencies for C extensions.
   - Verify wheels are available for `cp314t`.
   - Test for data races in extension code.

4. **Runtime flag verification**
   - CI gate should fail if `sys.flags.freethreading` is False when free-threading is required.

5. **CI gate automation**
   - Add a pre-commit hook that checks interpreter type.
   - Run integration tests under free-threaded interpreter.

6. **`uv` / `pyproject.toml` pinning guidance**
   - Pin Python version and interpreter build.
   - Document free-threaded requirement in README.

### Strategy

* Start with a compatibility audit of all dependencies.
* Use a canary deployment for free-threaded builds.
* Monitor for race conditions and performance regressions.
* Maintain a compatibility matrix for third-party packages.

## Relation to InterpreterPoolExecutor and run_in_thread

* `InterpreterPoolExecutor` (subinterpreters) provides parallelism with isolation. Use for CPU-bound pure-Python work with picklable arguments/results.
* `run_in_thread()` is the skill's single owner for offloading blocking/CPU-bound C extensions and I/O. It does not require free-threading.
* Free-threading is complementary: it enables parallelism within a single interpreter for pure-Python code that is already thread-safe. It does not replace `run_in_thread()` for C extensions.

Do not confuse the two. Free-threading does not make C extensions parallel; `InterpreterPoolExecutor` does not require free-threading.

## Known Limitations and Follow-Up

* Free-threaded Python 3.14 builds are not universally packaged; production adoption depends on platform availability.
* C-extension ecosystem support is still maturing; reference provides checks but cannot guarantee third-party wheels.
* AWS Lambda does not ship a free-threaded runtime; guidance is for ECS/VM workloads only.
* Shared mutable state remains a footgun; free-threading does not make unsafe code safe.

When in doubt, stick with the established patterns:
- I/O-bound work: `async/await` + `run_in_thread()` for blocking operations
- CPU-bound pure Python: `InterpreterPoolExecutor` (Python 3.14+) or evaluate free-threading
- CPU-bound C extensions: `run_in_thread()` (these already release the GIL effectively)

## Related Documentation

- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
- Consult `SKILL.md` for high-level skill conventions and recommendations
