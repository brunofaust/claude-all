# Free-threaded Python (no-GIL) — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## What is Free-threaded Python?

Free-threaded Python refers to a special build of Python 3.14+ where the Global Interpreter Lock (GIL) is made optional (via PEP 703). In this build, the GIL can be disabled at runtime, allowing multiple threads to execute Python bytecode in parallel without the GIL becoming a bottleneck.

This is different from the existing `InterpreterPoolExecutor` (PEP 734) approach, which uses subinterpreters to achieve parallelism by giving each interpreter its own GIL. The free-threaded build removes the GIL entirely from the Python interpreter, enabling true multithreaded parallelism for pure Python code.

**Note:** The free-threaded build is an experimental feature in Python 3.14 and must be explicitly installed. It is not the default build.

## When to Use

Consider using free-threaded Python when:

- You have **CPU-bound pure Python workloads** that are currently limited by the GIL.
- Your workload does **not rely on C extensions** that expect the GIL for thread safety (or you have verified those extensions are compatible with the no-GIL mode).
- You prefer **thread-based parallelism** over process-based or subinterpreter-based approaches for reasons such as:
  - Lower memory overhead (no need to duplicate interpreter state)
  - Faster context switching between threads
  - Easier sharing of mutable data between threads (with appropriate synchronization)
- You are already using threading in your codebase and want to remove the GIL bottleneck without changing your concurrency model.

Avoid free-threaded Python when:

- Your workload is **I/O-bound** (asyncio or `run_in_thread` are more appropriate).
- You depend on **C extensions that are not yet compatible** with disabled GIL (many popular libraries like NumPy, Pandas, Polars may require updates).
- You need **strong isolation between workers** (subinterpreters or processes provide better isolation).
- You are in a **regulated environment** where using an experimental Python build is not permitted.

## Pros and Cons

### Pros

- **True parallelism for CPU-bound pure Python code**: Multiple threads can run simultaneously on multiple cores.
- **Lower memory overhead** compared to `ProcessPoolExecutor` (no need to pickle data or duplicate interpreter state).
- **Faster thread creation and context switching** compared to processes.
- **Ability to share mutable data between threads** with standard threading primitives (locks, semaphores, etc.), though care must be taken to avoid race conditions.
- **Compatibility with existing threading code**: If your code already uses `threading.Thread` or `ThreadPoolExecutor`, you may be able to enable free-threading with minimal changes (if dependencies are compatible).

### Cons

- **Experimental feature**: The no-GIL build is new in Python 3.14 and may have bugs or performance issues.
- **C extension compatibility**: Many C extensions rely on the GIL for internal thread safety and may crash or behave incorrectly when the GIL is disabled.
- **Increased complexity in thread safety**: Without the GIL, data races can occur in pure Python code that previously relied on the GIL for atomicity (e.g., updating a list or dict from multiple threads).
- **Startup overhead**: Special builds may have slightly higher startup time or memory usage.
- **Tooling and debugging support**: Profilers, debuggers, and other tools may not yet fully support the no-GIL mode.
- **Limited adoption**: Fewer third-party libraries are tested and certified for no-GIL mode compared to the standard GIL-enabled build.

## How to Implement

### 1. Install a Free-threaded Python Build

You need to install a Python 3.14+ build that has been compiled with the `--disable-gil` flag. Options include:

- **Building from source**: Download Python 3.14 source and configure with `./configure --disable-gil --prefix=/opt/python/no-gil`
- **Using a distribution**: Some distributions (like conda-forge) may provide no-GIL builds. Check for packages labeled `python-no-gil` or similar.
- **Using pyenv**: Install via `pyenv install 3.14.0t` (the `t` suffix often indicates experimental thread-free builds).

Verify the build is free-threaded by checking:

```python
import sys
print(sys._is_gil_enabled())  # Should return False in no-GIL mode
```

Note: In the standard GIL-enabled build, `sys._is_gil_enabled()` returns `True`. In a free-threaded build, it returns `False` when the GIL is disabled (it can be toggled at runtime via `sys._gil_enabled()` in some implementations, but the baseline is without GIL).

### 2. Adjust Your Code for Thread Safety

With the GIL disabled, operations that were previously atomic (due to the GIL) may now require explicit synchronization. Review your code for:

- **Shared mutable state**: Variables, data structures, or objects accessed by multiple threads.
- **Non-atomic operations**: Operations like `list.append()`, `dict.update()`, or `x += 1` that involve multiple bytecode steps.

Use threading synchronization primitives from the `threading` module:

- `threading.Lock` for mutual exclusion
- `threading.RLock` for reentrant locks
- `threading.Semaphore` for limiting concurrent access
- `threading.Condition` for complex wait/notify patterns
- `queue.Queue` for thread-safe data passing

Example:

```python
import threading
from threading import Lock

# Shared counter
counter = 0
counter_lock = Lock()

def increment_counter():
    global counter
    with counter_lock:
        counter += 1  # Now safe without GIL

# Alternatively, use threading.local() for per-thread state
```

### 3. Use Threading Constructs

You can now use standard threading constructs without the GIL bottleneck:

```python
import threading
from concurrent.futures import ThreadPoolExecutor

def cpu_bound_work(n):
    # Pure Python CPU-bound work
    total = 0
    for i in range(n):
        total += i * i
    return total

# With free-threaded Python, this will utilize multiple cores
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(cpu_bound_work, 1000000) for _ in range(8)]
    results = [f.result() for f in futures]
```

### 4. Compare with Existing Patterns

In the `brunofaust-python-style` skill, we already have patterns for parallelism:

- **`run_in_thread`**: For offloading blocking I/O or C extension work (which may release the GIL) to a thread pool.
- **`InterpreterPoolExecutor`**: For CPU-bound pure Python work using subinterpreters (each with its own GIL).

With free-threaded Python, you may choose to replace `InterpreterPoolExecutor` or `run_in_thread` for CPU-bound pure Python work with a standard `ThreadPoolExecutor`, but only if:
- Your dependencies are verified compatible with no-GIL mode.
- You have addressed thread safety in your code.

## Dependency Compatibility Checking

### 1. Check for C Extensions

The main compatibility concern is C extensions that rely on the GIL for internal thread safety. To check:

- **Inspect your dependencies**: Use `pip list` or `pip freeze` to see installed packages.
- **Check for known incompatible packages**: Some popular packages may have announced support or lack thereof for no-GIL mode. Consult:
  - The Python Discord server's "no-gil" channel
  - The `pyproject.toml` or documentation of each dependency
  - Issue trackers for the packages (search for "no-gil" or "free-thread")
- **Use experimental tools**: Tools like `nogil-pip` or `cibuildwheel` may help identify compatibility, but they are not yet mature.

### 2. Runtime Checks

You can check at runtime whether the GIL is enabled:

```python
import sys

if not sys._is_gil_enabled():
    print("Running in no-GIL mode")
    # Add additional compatibility checks here if needed
else:
    print("Running with GIL enabled")
```

### 3. Testing Strategy

- **Run your test suite** in the no-GIL build to catch any failures.
- **Focus on multi-threaded tests**: Ensure that tests involving threads pass and do not exhibit data races or crashes.
- **Use stress tests**: Run your CPU-bound workloads with multiple threads to verify performance gains and stability.
- **Monitor for crashes or hangs**: C extensions that are not compatible may cause segmentation faults or deadlocks.

### 4. Known Compatible/Incompatible Packages (as of Python 3.14 release)

> **Note**: This information is subject to change. Always verify with the latest sources.

**Likely compatible** (pure Python or already GIL-aware):
- `requests` (HTTP I/O, releases GIL during network calls)
- `aiohttp` (async, but the sync parts may release GIL)
- `SQLAlchemy` (mostly releases GIL during DB I/O)
- `blinker` (pure Python)
- `attrs` (pure Python)
- `click` (pure Python)

**Potentially incompatible** (rely on GIL for thread safety in C extensions):
- `NumPy` (as of 3.14, experimental no-GIL support is in progress)
- `Pandas` (depends on NumPy)
- `Polars` (Rust FFI, may need updates)
- `PyTorch` (CUDA extensions may rely on GIL)
- `TensorFlow` (similar to PyTorch)
- `lxml` (C extension for XML parsing)
- `cryptography` (uses OpenSSL, may have GIL assumptions)

**Check each package individually** — many are actively working on no-GIL compatibility.

## See Also

- [`async-patterns.md`](async-patterns.md): Covers `run_in_thread` and `InterpreterPoolExecutor` for parallelism in async Python.
- [`testing.md`](testing.md): Guidance on testing multi-threaded code.
- [`type-hints.md`](type-hints.md): For using type hints to document thread-safety assumptions.

## Changelog

- Initial version: Added reference for free-threaded Python 3.14 feature.
