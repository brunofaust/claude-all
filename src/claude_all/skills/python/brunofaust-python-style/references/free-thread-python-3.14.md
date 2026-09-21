# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Free-Threading Overview

Python 3.13 introduced free-threaded builds (also called *no-GIL* builds) and Python 3.14 stabilizes and extends this feature. A free-threaded interpreter removes the global interpreter lock (GIL), allowing multiple threads to execute Python bytecode in parallel on multiple CPU cores.

This is different from `multiprocessing` and from `InterpreterPoolExecutor` (PEP 734 subinterpreters):

- **Free-threading**: Single interpreter, multiple OS threads execute Python code in parallel. Best for pure-Python CPU-bound workloads.
- **InterpreterPoolExecutor**: Multiple subinterpreters, each with its own GIL, communicating via pickling. Best for CPU-bound work with strict isolation.
- `run_in_thread()`: Offloads blocking I/O/C extensions to threads; threads do not run Python bytecode in parallel due to the GIL.

Free-threading works at the interpreter level. The interpreter must be built with the `PYTHON_GIL=0` configuration. Once built, the Python runtime enables parallel execution of Python code without the GIL. C extensions that release the GIL (e.g., NumPy, asyncio) already benefit from threading; pure-Python code gains true parallelism.

## When to Use Free-Threading

Use free-threaded Python 3.14 when:

| Condition | Use Free-Threading? | Notes |
|-----------|---------------------|-------|
| Pure-Python CPU-bound computations (e.g., data transformation loops, algorithms) | Yes — ideal case | Threads execute Python bytecode in parallel |
| Mixed CPU + I/O workloads with blocking C extensions | Maybe — use `run_in_thread()` instead | C extensions already release GIL; free-threading adds complexity |
| Code relies heavily on shared mutable state | No — major risk | Race conditions, no protection |
| Large codebases using third-party libraries | No — compatibility check required | Many libraries are not free-thread safe |
| Need cross-interpreter isolation (security, memory protection) | No — use `InterpreterPoolExecutor` | Subinterpreters provide isolation |

### Typical Use Cases

- Data processing pipelines written in pure Python that are CPU-bound
- Scientific computing with pure-Python algorithms (not C extensions)
- Parallel task processing where each task is independent and stateless
- Microservices with CPU-bound request handlers that can be fully free-threaded
- Batch jobs that can be refactored to avoid shared mutable state

Avoid free-threading when:
- The codebase is async-first and I/O-bound (the GIL is already mostly released)
- Heavy use of third-party C extensions with Python state (e.g., SQLAlchemy core, some ORMs)
- Shared global caches, singletons, or in-process state machines

## Pros and Cons

### Advantages

1. **True parallelism for pure-Python code**
   Multiple threads execute Python bytecode simultaneously on multiple cores. No need for multiprocessing overhead.

2. **Lower memory overhead vs multiprocessing**
   Threads share memory; no serialization/deserialization cost.

3. **Simpler programming model**
   Existing threading code works without major changes. No process boundaries to manage.

4. **Better for fine-grained parallelism**
   Suitable for workloads with many small tasks where process overhead is high.

### Disadvantages

1. **Thread safety required**
   Code must be safe for concurrent access. Global interpreter lock previously hid many race conditions.

2. **Shared mutable state becomes a problem**
   Race conditions can appear where they were previously impossible. Need explicit synchronization.

3. **C extension compatibility**
   Extensions must be compiled with free-thread support. Many are not yet compatible.

4. **Pickling limitations remain**
   Some patterns still require pickling for thread-safe data sharing.

5. **Debugging complexity**
   Concurrency bugs are harder to reproduce and diagnose.

6. **Limited ecosystem support**
   Python 3.14 free-threading is recent; many libraries lack official support.

## Implementation

### Setup

Ensure Python is built with free-threading enabled:

```bash
python -c "import sys; print(sys._is_gil_enabled())"
```

Expected output:
```
False
```

If `True`, the interpreter is GIL-enabled and free-threading is not active.

Set the environment variable to prefer free-threaded builds if available:

```bash
PYTHON_GIL=0 python myapp.py
```

### Basic Usage

Free-threading works transparently with existing `threading.Thread` code:

```python
import threading
from concurrent.futures import ThreadPoolExecutor
from myapp.core.thread_pool import run_in_thread

def cpu_intensive_task(n):
    total = 0
    for i in range(n):
        total += i * i
    return total

# With free-threading, this runs in parallel
def process_items(items):
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(cpu_intensive_task, item) for item in items]
        return [f.result() for f in futures]
```

For async code, combine with `run_in_thread()` for blocking pure-Python CPU work:

```python
from myapp.core.thread_pool import run_in_thread

async def handle_request(data):
    # Offload CPU-bound pure Python to thread pool
    result = await run_in_thread(cpu_intensive_task, data)
    return result
```

### Hybrid CPU + I/O Workloads

When work mixes CPU computation and I/O (especially C extensions):

1. Keep I/O in async with `run_in_thread()` for C extensions.
2. Offload pure-Python CPU parts to free-threaded threads.
3. Avoid shared mutable state between threads.

```python
import asyncio
from myapp.core.thread_pool import run_in_thread
from concurrent.futures import ThreadPoolExecutor

def pure_python_compute(payload):
    # CPU-bound pure Python
    return sum(x*x for x in payload)

async def fetch_and_process(url):
    # I/O via async (e.g., aiohttp)
    data = await fetch_data(url)  # async I/O

    # CPU via thread pool
    result = await run_in_thread(pure_python_compute, data)
    return result
```

**Guidance**: Prefer `InterpreterPoolExecutor` (Python 3.14+) for CPU-bound pure Python tasks that require isolation. Free-threading is most valuable when:

- Latency matters and process overhead is too high
- Work shares read-only data structures
- Code cannot be easily refactored into separate processes

### Thread Safety Practices

- Avoid mutable global state. Use local variables.
- Use `threading.Lock`, `RLock` for shared mutable data.
- Prefer immutable data structures for inter-thread communication.
- Document assumptions about thread safety in function docstrings.
- Use `concurrent.futures.ThreadPoolExecutor` with appropriate `max_workers` (typically `os.cpu_count()`).

## Dependency Compatibility

### Checking Compatibility

1. **Python version**: Must be 3.14+ with free-thread enabled (`sys._is_gil_enabled()` returns `False`).
2. **C extensions**: Check if compiled with `Py_mod_gil = Py_MOD_PER_INTERPRETER` support.
   - Use `pip list` and check vendor documentation.
   - Search for "free-threading" or "GIL" in release notes.
3. **Standard library**: Most stdlib modules are compatible; `threading` and `concurrent.futures` work natively.
4. **Third-party libraries**: Verify support status.

### Compatibility Checklist

```
□ Python 3.14+ free-threaded build installed
□ No usage of asyncio.to_thread (use run_in_thread())
□ No reliance on GIL for thread safety
□ No shared mutable globals without locks
□ C extensions verified compatible or offloaded
□ Tests run with GIL disabled
□ Picklable data for inter-thread communication
□ Documentation updated for concurrency assumptions
```

### Strategies

- **Gradual adoption**: Run free-threaded interpreter in dev; keep CI on GIL-enabled for stability.
- **Isolation**: Use `InterpreterPoolExecutor` for untrusted/legacy code.
- **Fallback**: Detect GIL status at runtime and adjust thread pool size.
- **Vendor testing**: Test third-party libraries in free-threaded environment before production.

### Common Incompatible Patterns

- Libraries that rely on GIL for implicit synchronization
- Extensions using CFFI with Python callbacks that assume GIL
- Code using `multiprocessing` based on `fork` with shared memory expectations
- Custom C extensions not compiled with free-thread support

## Related Documentation

- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
- Consult `SKILL.md` for high-level skill conventions and recommendations
