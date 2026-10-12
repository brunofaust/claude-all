# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces an optional free-threaded build (PEP 703) that disables the Global Interpreter Lock (GIL), allowing true parallelism in multithreaded Python programs. This is a significant change from the traditional CPython model where the GIL prevents multiple threads from executing Python bytecode simultaneously.

### Relation to GIL
- **Traditional CPython**: Single GIL ensures thread safety but limits CPU-bound parallelism
- **Free-threaded build**: No GIL, enabling multiple threads to run Python code in parallel
- **Availability**: Only in special free-threaded builds of Python 3.14+ (not the default)
- **Detection**: Use `sys._is_gil_enabled()` to check at runtime

### Relation to InterpreterPoolExecutor (PEP 734)
While both provide parallelism, they serve different purposes:
- **Free-threading**: Shares memory space, lower overhead, requires careful synchronization
- **InterpreterPoolExecutor**: Uses subinterpreters with separate GILs, better isolation, higher overhead
- **Project guidance**: Prefer `InterpreterPoolExecutor` for CPU-bound pure Python when isolation is needed; use free-threading only when shared state is required and properly managed

## When to Use

### Appropriate Use Cases
- **CPU-bound pure Python workloads** where threads can share data efficiently
- **Applications requiring low-latency thread communication** (shared memory avoids serialization)
- **Scenarios where process overhead of multiprocessing is prohibitive**
- **Gradual migration path** from threaded code that already handles shared state correctly

### Inappropriate Use Cases
- **I/O-bound work**: Use `async/await` + `run_in_thread()` instead
- **CPU-bound C extensions**: Use `run_in_thread()` (these already release the GIL effectively)
- **Code with complex shared state**: Risk of race conditions increases significantly
- **Libraries not verified for free-threaded compatibility**: May crash or behave unpredictably

## Pros and Cons

### Pros
- **True parallelism**: Multiple CPU cores utilized for Python code execution
- **Lower overhead**: No process creation/serialization costs unlike multiprocessing
- **Shared memory space**: Easy data sharing between threads without serialization
- **Compatible with existing threading models**: Familiar `threading.Thread` API
- **Gradual adoption**: Can enable free-threading only for specific workloads

### Cons
- **Increased complexity**: Race conditions and synchronization bugs more likely
- **Debugging difficulty**: Non-deterministic behavior harder to reproduce
- **Extension compatibility**: C extensions must be audited for thread safety
- **Memory visibility**: Requires proper use of `volatile`/atomic operations or locks
- **Build availability**: Requires special free-threaded Python builds (not default)
- **Performance variability**: Contention on shared resources can degrade performance

## How to Implement

### Basic Usage
```python
# Example: Using free-threading for CPU-bound work with proper synchronization
import threading
import sys
from threading import Lock

def cpu_bound_work(n, lock, counter):
    """CPU-bound function that increments a shared counter."""
    local_sum = 0
    for i in range(n):
        local_sum += i * i

    # Safely update shared state
    with lock:
        counter[0] += local_sum

def main():
    # Check if running in free-threaded build
    if sys._is_gil_enabled():
        print("Warning: Running in GIL-enabled mode. Free-threading not available.")
        print("To test free-threading, install a free-threaded Python 3.14+ build.")
        return

    # Shared state with protection
    lock = Lock()
    counter = [0]  # Using list for mutability in closure

    # Create threads for parallel execution
    threads = []
    num_threads = 4
    work_per_thread = 1000000

    for i in range(num_threads):
        t = threading.Thread(target=cpu_bound_work, args=(work_per_thread, lock, counter))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    print(f"Final counter value: {counter[0]}")
    print(f"Expected value: {num_threads * sum(i*i for i in range(work_per_thread))}")

if __name__ == "__main__":
    main()
```

### Hybrid Approach (CPU + I/O)
```python
# Example: Combining free-threading for CPU work with async for I/O
import asyncio
import threading
import sys
import aiohttp
from threading import Lock

def cpu_intensive_task(data_chunk, lock, result_list):
    """CPU-intensive processing with thread-safe result collection."""
    local_result = 0
    for item in data_chunk:
        # Simulate CPU work (e.g., hashing, computation)
        local_result += hash(item) & 0xFFFFFFFF  # Keep within 32-bit

    # Safely append result
    with lock:
        result_list.append(local_result)

async def fetch_url(session, url):
    """I/O-bound HTTP fetch."""
    try:
        async with session.get(url) as response:
            return await response.text()
    except Exception:
        return None

async def main():
    if sys._is_gil_enabled():
        print("Warning: Running in GIL-enabled mode.")
        print("Free-threading features will not work in this Python build.")
        # Fallback to existing patterns
        return

    # Shared state for CPU work results
    cpu_lock = Lock()
    cpu_results = []

    # Prepare data chunks for CPU work
    data_chunks = [list(range(i*1000, (i+1)*1000)) for i in range(20)]

    # Launch CPU-bound threads
    cpu_threads = []
    for chunk in data_chunks:
        t = threading.Thread(
            target=cpu_intensive_task,
            args=(chunk, cpu_lock, cpu_results)
        )
        cpu_threads.append(t)
        t.start()

    # Launch I/O-bound async tasks
    async with aiohttp.ClientSession() as session:
        urls = ["https://httpbin.org/delay/1"] * 10
        io_tasks = [fetch_url(session, url) for url in urls]
        io_results = await asyncio.gather(*io_tasks, return_exceptions=True)

    # Wait for CPU threads to complete
    for t in cpu_threads:
        t.join()

    # Filter out exceptions from IO results
    successful_io = [r for r in io_results if not isinstance(r, Exception)]

    print(f"CPU results: {len(cpu_results)} chunks processed")
    print(f"IO results: {len(successful_io)} successful requests")
    print(f"Sample CPU result: {cpu_results[0] if cpu_results else 'None'}")

if __name__ == "__main__":
    asyncio.run(main())
```

## Dependency Compatibility

### Checking if Dependencies Support Free-Threading
Before enabling free-threading in your application, verify that your dependencies are compatible.

#### 1. Pure Python Modules
- **Check for module-level state**: Ensure any global or class-level state is thread-safe
- **Review synchronization patterns**: Look for proper use of locks, threading.local, or atomic operations
- **Test with concurrent access**: Run stress tests with multiple threads accessing the module

#### 2. C Extensions (Critical)
- **GIL release verification**: Confirm extensions release the GIL during blocking operations
  - Look for `Py_BEGIN_ALLOW_THREADS` / `Py_END_ALLOW_THREADS` in source
  - Check documentation for threading notes
- **Thread safety audit**: Ensure extension doesn't rely on GIL for internal data protection
- **Runtime testing**: Use `faulthandler` and stress tests to detect crashes or corruption

#### 3. Third-Party Packages
- **Consult documentation**: Search for "free-threaded", "PEP 703", or "no-GIL" in docs
- **Check issue trackers**: Look for reported free-threading compatibility issues
- **Test in isolation**: Verify package works correctly in a free-threaded environment
- **Contact maintainers**: When in doubt, ask about free-threading support plans

### Project-Specific Guidelines
Based on the `brunofaust-python-style` skill conventions:

#### Preferred Patterns
- **I/O-bound work**: Continue using `async/await` + `run_in_thread()` for blocking operations
- **CPU-bound pure Python**:
  - Prefer `InterpreterPoolExecutor` (Python 3.14+) for isolated parallelism
  - Consider free-threading only when shared state is unavoidable and properly synchronized
- **CPU-bound C extensions**: Use `run_in_thread()` (these already release the GIL effectively)
- **Avoid raw threading**: Use project-provided wrappers for consistent behavior

#### Banned API Rules
Refer to `enforcement.md` for specific banned-api rules:
- Raw `threading.Thread` usage may be restricted in favor of managed pools
- Direct lock usage should follow project conventions
- Global module state must be audited for thread safety

#### Validation Checklist
Before deploying with free-threading enabled:
- [ ] Confirm Python build is free-threaded (`sys._is_gil_enabled()` returns `False`)
- [ ] Audit all direct `threading.Thread` usage for proper synchronization
- [ ] Review C extensions for thread-safety and GIL release practices
- [ ] Test third-party packages in free-threaded environment
- [ ] Run existing test suite with free-threading to catch regressions
- [ ] Monitor production for performance degradation or corruption symptoms

## Related Documentation
- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
- Consult `SKILL.md` for high-level skill conventions and recommendations
