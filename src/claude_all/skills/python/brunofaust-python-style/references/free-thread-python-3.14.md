# Python 3.14 Free-Threading — Reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

Python 3.14 can be built with free-threading — the GIL is disabled at interpreter build time. This enables true parallelism within a single process by using `concurrent.futures.InterpreterPoolExecutor` (PEP 734). Free-threading is **not** the same as `run_in_thread()`; it is a different concurrency primitive for CPU-bound pure-Python work.

Free-threading does not make shared mutable state safe. The skill's async-first, GIL-related guidance in `async-patterns.md` and the `run_in_thread()` pattern remain the default for I/O and C-extension work.

## Overview

Free-threaded Python 3.14 removes the Global Interpreter Lock when the interpreter is built with `--disable-gil`. Each subinterpreter in `InterpreterPoolExecutor` has its own GIL and its own Python runtime state.

**Key facts**

- Available on Python 3.14+ with a free-threaded build.
- `concurrent.futures.InterpreterPoolExecutor` is the primary API. It provides true parallelism for CPU-bound pure-Python code with lower overhead than `ProcessPoolExecutor`.
- Arguments and return values must be picklable. Only a limited set of shareable types bypass pickling: `str | bytes | int | float | bool | None | tuple | memoryview`.
- C extensions that hold global mutable state, use thread-local storage incorrectly, or assume GIL protection will not be safe under free-threading.
- `run_in_thread()` remains the owner of thread-offload seams for blocking/C-extension work. `asyncio.to_thread` and raw `ThreadPoolExecutor` are banned by the skill's `banned-api` rules.

## When to Use

Use free-threading with `InterpreterPoolExecutor` **only** for CPU-bound pure-Python workloads that are embarrassingly parallel and have no shared mutable state.

| Situation | Use |
| --- | --- |
| CPU-bound pure Python (parsing, math, pure algorithm) | `InterpreterPoolExecutor` — true parallelism |
| CPU-bound C extension (Polars, NumPy, DeltaTable) | `run_in_thread()` — C extensions already release the GIL |
| Blocking I/O (file, network, SDK) | `run_in_thread()` — simpler, lower overhead |
| Needs shared mutable state | `run_in_thread()` — interpreters are isolated |
| Needs async coordination per task | `asyncio.TaskGroup` + `run_in_thread()` |

**Do not use free-threading for Lambda.** AWS Lambda does not ship a free-threaded Python 3.14 runtime. Guidance is limited to ECS/VM workloads where you control the interpreter build.

## Pros / Cons

**Pros**

- True parallelism for pure-Python CPU work without multiprocessing overhead.
- Lower memory footprint than `ProcessPoolExecutor`; subinterpreters share read-only code objects.
- Fits the skill's async-first model as a CPU offload primitive alongside `run_in_thread()` for I/O.

**Cons**

- Shared mutable state remains unsafe; free-threading does not fix race conditions, it exposes them.
- Pickling constraint: arguments/results must be picklable. Non-picklable objects cannot cross interpreter boundaries.
- C-extension ecosystem support is still maturing. Many wheels are not free-thread safe.
- Only works on platforms that provide a free-threaded interpreter build. AWS Lambda does not.
- Debugging and observability of subinterpreters is harder than threads.

## Implementation

### Basic CPU-bound use

```python
from concurrent.futures import InterpreterPoolExecutor

def compute_square(x: int) -> int:
    return x * x

with InterpreterPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(compute_square, range(100)))
```

`InterpreterPoolExecutor` is the skill-allowed way to get true parallelism for pure-Python CPU work. It is explicitly covered in `async-patterns.md`.

### Hybrid CPU + I/O pattern

CPU work via `InterpreterPoolExecutor`, I/O/blocking via `run_in_thread()`:

```python
import asyncio
from concurrent.futures import InterpreterPoolExecutor
from thread import run_in_thread  # skill's thread pool owner

def cpu_heavy(item: dict) -> dict:
    # pure Python CPU work, no shared state
    return {k: v * 2 for k, v in item.items()}

async def process_batch(items: list[dict]) -> list[dict]:
    # Parallel CPU stage
    with InterpreterPoolExecutor() as pool:
        cpu_results = list(pool.map(cpu_heavy, items))

    # I/O stage — blocking library offloaded to thread pool
    results = []
    for r in cpu_results:
        processed = await run_in_thread(expensive_c_extension_fn, r)
        results.append(processed)
    return results
```

Never use `asyncio.to_thread` directly. The skill bans it via `banned-api` and requires `run_in_thread()` as the single owner of the thread-offload seam.

### Interaction with skill conventions

- Prefer `InterpreterPoolExecutor` for CPU-bound pure Python.
- Prefer `run_in_thread()` for C-extension work, file I/O, and blocking SDK calls.
- `asyncio.to_thread` and direct `ThreadPoolExecutor` usage are banned. See `enforcement.md`.
- Free-threading does not change the async-first rule: custom functions are `async def`, I/O stays async, CPU offload is isolated.
- Shared mutable state remains unsafe under free-threading. Treat all interpreter boundaries as process boundaries.

## Compatibility

### Interpreter verification

```python
import sys
import sysconfig

# Interpreter was built with free-threading enabled
freethreaded = sys.flags.freethreading  # bool, Python 3.13+

# Build config inspection
build = sysconfig.get_config_var("Py_GIL_DISABLED")
print(f"freethreading flag: {freethreaded}, Py_GIL_DISABLED: {build}")
```

Gate on interpreter capability at import time:

```python
if not sys.flags.freethreading:
    raise RuntimeError("Free-threaded Python 3.14+ is required for this module")
```

### Wheel ABI inspection

Free-threaded wheels use the `cp314t` ABI tag (`t` = free-threaded). Verify installed wheels:

```bash
python -c "import sysconfig; print(sysconfig.get_config_var('SOABI'))"
# cp314t → free-threaded, cp314 → classic
```

Inspect package metadata for ABI compatibility before upgrading dependencies.

### C-extension compatibility checklist

A dependency is compatible only if **all** are true:

- Wheel is built for `cp314t` or ships a pure-Python implementation.
- The extension does not rely on global mutable state or `PyEval_SaveThread`-only assumptions.
- The extension vendor documents free-thread support.
- No use of C-API functions that are not free-thread safe.

For each direct dependency, record:

- Pure Python? → safe
- C extension with `cp314t` wheel? → likely safe, test
- C extension only `cp314`? → incompatible

### Runtime flag verification

CI should verify both interpreter and runtime behavior:

```python
def test_freethreading_enabled():
    import sys
    assert sys.flags.freethreading, "Interpreter not free-threaded"

def test_interpreter_pool_executor():
    from concurrent.futures import InterpreterPoolExecutor
    with InterpreterPoolExecutor(max_workers=2) as ex:
        assert ex.submit(lambda: 1+1).result() == 2
```

### CI gate automation

Add a `prek.toml` gate to enforce free-threaded interpreter in CI:

```toml
[[repos]]
repo = "local"
hooks = [
  { id = "python-freethread-check", entry = "python -c \"import sys; exit(0 if sys.flags.freethreading else 1)\", language = "system", stages = ["pre-commit"] }
]
```

Reference `pyproject.toml` to pin Python:

```toml
[project]
requires-python = ">=3.14"
 classifiers = [
   "Programming Language :: Python :: 3.14",
   "Programming Language :: Python :: Implementation :: CPython :: Free Threading"
 ]
```

### Platform and runtime limitations

- AWS Lambda does not ship a free-threaded Python 3.14 runtime. Do not rely on free-threading for Lambda workloads; use ECS/VM workloads where the interpreter is controlled.
- Shared mutable state remains unsafe. Free-threading exposes races; it does not prevent them. Use immutable data and explicit boundaries across interpreters.
- Debugging with `pdb` or profilers may be less mature for subinterpreters.
- Only picklable arguments/results are supported between interpreters.

See also `async-patterns.md` for `InterpreterPoolExecutor` vs `run_in_thread()` guidance, `enforcement.md` for banned-API rules, and `SKILL.md` for high-level skill conventions.
