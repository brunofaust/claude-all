# Free-threading (PEP 703) — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

- **CPU-bound Python code** that currently suffers from GIL contention and can benefit from true parallelism.
- **Workloads with minimal shared mutable state** (or where state can be partitioned) to avoid complex synchronization.
- **When targeting the experimental free-threading build of Python 3.14** (not the default build) and willing to manage compatibility trade-offs.
- **Not for I/O-bound work** — asyncio and threading already handle I/O efficiently; free-threading adds complexity without benefit.
- **Not for extension-heavy workloads** — C extensions must be updated to be free-thread compatible; many are not yet.

## Core Concepts

Python 3.14 includes an experimental free-threading build (enabled via `--disable-gil` at compile time) that removes the Global Interpreter Lock (GIL), allowing multiple threads to execute Python bytecode in parallel. This is not the default build; it is a separate interpreter mode.

Key implications:
- **True parallelism** for CPU-bound Python code (no GIL bottleneck).
- **Thread safety becomes critical** — existing code relying on GIL for atomicity (e.g., `list.append`, `dict.update`) may now require explicit locks.
- **Extension modules must be updated** — any C extension that touches Python objects must use the new per-interpreter GIL or external synchronization.
- **Memory overhead increases** slightly due to per-interpreter locks and reference counting changes.

## Implementation Approach

### 1. Detecting Free-threading Capability

At runtime, check if the interpreter is free-threading enabled:

```python
import sys

def is_freethreading_enabled():
    """Return True if running in a free-threading Python build."""
    return hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled()
```

### 2. Adapting Code for Free-threading

When free-threading is enabled, adjust synchronization strategies:

#### a. Replace GIL-reliant atomic operations

Operations that were atomic under the GIL (due to bytecode granularity) are no longer atomic. Use threading primitives for shared state.

```python
import threading
from threading import Lock

# Under GIL: this was atomic (thread-safe for single operations)
# In free-threading: requires lock for compound operations
shared_counter = 0
counter_lock = Lock()

def increment_counter():
    global shared_counter
    with counter_lock:
        shared_counter += 1  # Now safe under free-threading
```

#### b. Use thread-safe data structures

Consider using `queue.Queue` or `collections.deque` with locks for shared collections, or explore `multiprocessing.managers` for shared state.

#### c. Extension compatibility

Verify that all C extensions used are free-thread compatible. Check:
- Extension documentation for free-threading support.
- Whether the extension uses the new PyInterpreterState APIs or external locks.
- Test extensions in free-threading mode before deployment.

### 3. Leveraging Free-threading for Parallelism

Use `threading.Thread` or `concurrent.futures.ThreadPoolExecutor` for CPU-bound tasks that release the GIL (or now run in parallel).

```python
from concurrent.futures import ThreadPoolExecutor
import threading

def cpu_bound_task(data):
    # Perform computation that now runs in parallel on free-threading build
    result = sum(x * x for x in data)
    return result

def process_data_parallel(data_chunks):
    if is_freethreading_enabled():
        # Use thread pool for true parallelism
        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(cpu_bound_task, chunk) for chunk in data_chunks]
            return [f.result() for f in futures]
    else:
        # Fall back to process pool or async offloading for CPU-bound work
        # (existing strategy for GIL-constrained Python)
        from ..thread import run_in_thread  # assuming run_in_thread utility
        import asyncio

        async def process():
            tasks = [run_in_thread(cpu_bound_task, chunk) for chunk in data_chunks]
            return await asyncio.gather(*tasks)

        return asyncio.run(process())
```

### 4. Configuration and Deployment

- **Environment setup**: Use the free-threading Python build (e.g., from `conda-forge` or self-compiled with `--disable-gil`).
- **Dependency validation**: Run your test suite in free-threading mode to catch threading issues.
- **Monitoring**: Watch for increased latency due to lock contention or extension incompatibilities.

## Pros and Cons

### Pros

| Advantage                | Description                                                                 |
|--------------------------|-----------------------------------------------------------------------------|
| **True parallelism**     | CPU-bound Python threads run in parallel on multi-core systems.             |
| **Lower overhead**       | Avoids process creation/serialization costs of `multiprocessing`.           |
| **Simpler sharing**      | Threads share memory space natively (no need for IPC or pickling).          |
| **Incremental adoption** | Can enable free-threading per-interpreter; fallback to GIL mode if needed.  |

### Cons

| Disadvantage             | Description                                                                 |
|--------------------------|-----------------------------------------------------------------------------|
| **Extension incompatibility** | Many C extensions (e.g., NumPy, Pandas, cryptography) require updates.    |
| **Increased complexity** | Thread safety audits required; locks needed for previously atomic operations. |
| **Memory overhead**      | Slightly higher memory usage due to per-interpreter locks.                  |
| **Debugging difficulty** | Race conditions and deadlocks are harder to reproduce and diagnose.         |
| **Limited tooling**      | Profilers and debuggers may not fully support free-threading yet.           |

## Dependency Compatibility Checking

### 1. Automated Checks

- **Use `sys._is_gil_enabled()`** in CI to fail builds if dependencies are not verified.
- **Run test suite in free-threading mode** as part of the CI matrix.
- **Leverage `pip check`** and `pipdeptree` to identify known-incompatible packages.

### 2. Manual Verification

For each dependency:
1. Check the project's documentation for free-threading/Python 3.14 notes.
2. Look for issues or PRs related to "free-threading", "disable-gil", or "PEP 703".
3. Test the dependency in isolation with a free-threading interpreter:
   ```python
   import dependency
   # Exercise code paths that use Python objects extensively
   ```
4. Check if the extension uses the new `PyInterpreterState*` APIs (source inspection).

### 3. Community Resources

- **Python C-API Compatibility Guide**: https://docs.python.org/3/c-api/gil.html
- **Free-threading compatibility wiki**: https://github.com/python/cpython/wiki/Disable-GIL
- **Tracked compatibility**: https://github.com/encukou/pyfreethreading

### 4. Fallback Strategy

Design modules to detect free-threading capability and adapt:

```python
import sys
from threading import Lock

# Shared state protected by lock only when needed
_shared_state = {}
_state_lock = Lock()  # Used conditionally

def update_shared(key, value):
    if sys._is_gil_enabled():
        # GIL mode: atomic for dict assignment (bytecode level)
        _shared_state[key] = value
    else:
        # Free-threading: require lock for dict assignment
        with _state_lock:
            _shared_state[key] = value
```

## Best Practices

1. **Prefer process parallelism for extension-heavy workloads** — use `multiprocessing` or `concurrent.futures.ProcessPoolExecutor` when dependencies are not free-thread ready.
2. **Minimize shared state** — use message-passing (queues) or immutable data structures to reduce locking needs.
3. **Audit hot paths** — profile to identify contention points and optimize lock granularity.
4. **Version pinning** — pin dependencies to verified free-threading-compatible versions.
5. **Feature flags** — allow disabling free-threading per-deployment via environment variable.
6. **Testing** — run stress tests with thread sanitizers (e.g., `TSAN`) to detect race conditions.

## When to Stick with GIL Mode

- **Default Python 3.14 build** (with GIL) remains the safest choice for most applications.
- **I/O-bound applications** — asyncio and threading already scale well; free-threading adds no benefit.
- **Extension-dependent workloads** — if key dependencies lack free-threading support, the compatibility work may outweigh gains.
- **Teams without threading expertise** — free-threading introduces subtle concurrency bugs that require deep understanding.

## References

- PEP 703 – Making the Global Interpreter Lock Optional in CPython: https://peps.python.org/pep-0703/
- Python 3.14 release notes (free-threading section): https://docs.python.org/3/whatsnew/3.14.html#free-threading-support
- Discuss mailing list: https://discuss.python.org/c/python-dev/
