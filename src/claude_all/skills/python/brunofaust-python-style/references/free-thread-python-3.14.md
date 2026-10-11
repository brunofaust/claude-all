# Free-thread Python 3.14 — Full Reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces **free-threaded execution** via PEP 703, which makes the Global Interpreter Lock (GIL) optional. When built with the `--disable-gil` flag, Python objects become thread-safe for concurrent access, enabling true parallelism using OS threads without the GIL bottleneck.

This is distinct from but related to:
- **Subinterpreters** (PEP 734, `InterpreterPoolExecutor`) — provides isolation via separate interpreters, each with its own GIL
- **Free-threading** — removes the GIL entirely, allowing threads to run in parallel on multi-core systems

When free-threading is enabled, `threading.Thread` and `concurrent.futures.ThreadPoolExecutor` can achieve true parallelism for CPU-bound workloads, similar to `ProcessPoolExecutor` but with lower memory overhead and easier sharing of objects (when using immutable or thread-safe patterns).

## When to Use

- **CPU-bound pure Python workloads** that can be parallelized (e.g., numerical computations, data parsing, simulations)
- **Workloads where ProcessPoolExecutor overhead is prohibitive** (high memory cost of pickling/unpickling, complex object sharing)
- **Scenarios where you need thread-level parallelism** but want to avoid the complexity of process-based parallelism

**Not recommended for:**
- I/O-bound work (use `async/await` + `run_in_thread()` for blocking operations)
- Workloads requiring shared mutable state without proper synchronization
- Environments where third-party dependencies are not free-thread compatible

## Pros and Cons

### Pros
- **True parallelism**: Multiple Python threads can execute Python bytecode in parallel on multiple cores
- **Lower overhead**: Compared to `ProcessPoolExecutor` — no process creation, no IPC serialization costs for shared data
- **Familiar threading model**: Uses standard `threading` module and `ThreadPoolExecutor`
- **Easier data sharing**: Objects can be shared between threads without pickling (when using proper synchronization)
- **Gradual adoption**: Can be enabled per-interpreter; existing GIL-mode code continues to work

### Cons
- **Shared mutable state requires synchronization**: Unlike the GIL which implicitly serialized access, free-threading demands explicit locking for shared mutable state
- **Dependency compatibility**: All C extensions and pure Python modules must be free-thread safe
- **Debugging complexity**: Race conditions and deadlocks are more likely and harder to reproduce
- **Performance variability**: Some workloads may see slower performance due to increased locking overhead or cache contention
- **Limited Windows support**: Free-threaded builds may have platform-specific considerations

## Implementation

### Basic Usage with ThreadPoolExecutor

```python
from concurrent.futures import ThreadPoolExecutor
import threading


def cpu_bound_work(n: int) -> int:
    """Example CPU-bound computation."""
    total = 0
    for i in range(n):
        total += i * i
    return total


def parallel_compute(numbers: list[int]) -> list[int]:
    """Process numbers in parallel using ThreadPoolExecutor."""
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Map the CPU-bound function across the input list
        results = list(executor.map(cpu_bound_work, numbers))
    return results


# Example usage
if __name__ == "__main__":
    numbers = [100000, 200000, 150000, 300000]
    results = parallel_compute(numbers)
    print(f"Results: {results}")
```

### Hybrid CPU + I/O Workloads

For workloads that combine CPU-bound computation with I/O operations, combine free-threading with async patterns:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List


async def process_data_item(item: dict) -> dict:
    """Process a single data item with CPU work and I/O."""
    # CPU-bound preprocessing (can run in thread pool)
    processed = await run_in_thread(_cpu_intensive_transform, item["raw_data"])

    # Simulate I/O operation (already async)
    result = await _save_to_database(processed, item["id"])

    return result


def _cpu_intensive_transform(raw_data: str) -> dict:
    """CPU-intensive data transformation."""
    # Example: parsing, validation, computation
    parsed = {"length": len(raw_data), "words": raw_data.split()}
    # Simulate more work
    for i in range(10000):
        parsed["checksum"] = sum(ord(c) * i for c in raw_data[:100])
    return parsed


async def _save_to_database(data: dict, item_id: str) -> dict:
    """Simulate async database save."""
    # In reality, this would be an async DB call
    await asyncio.sleep(0.01)  # Simulate network delay
    return {"id": item_id, "status": "saved", "data": data}


async def run_in_thread(func, *args):
    """Helper to run blocking CPU work in thread pool."""
    loop = asyncio.get_running_loop()
    # In a free-threaded Python 3.14 build, this uses native threads
    # without GIL contention for pure Python work
    return await loop.run_in_executor(None, func, *args)


async def main():
    """Example async main processing multiple items."""
    items = [
        {"id": "1", "raw_data": "sample data one"},
        {"id": "2", "raw_data": "another sample"},
        {"id": "3", "raw_data": "more data to process"},
    ]

    # Process items concurrently
    tasks = [process_data_item(item) for item in items]
    results = await asyncio.gather(*tasks)

    for result in results:
        print(f"Processed: {result}")


if __name__ == "__main__":
    asyncio.run(main())
```

### Using Shared State Safely

When sharing mutable state between threads in free-threaded mode, use appropriate synchronization primitives:

```python
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List


class ThreadSafeCounter:
    """Thread-safe counter using a lock."""

    def __init__(self):
        self._value = 0
        self._lock = threading.Lock()

    def increment(self) -> int:
        """Increment the counter and return the new value."""
        with self._lock:
            self._value += 1
            return self._value

    @property
    def value(self) -> int:
        """Get the current value (thread-safe read)."""
        with self._lock:
            return self._value


def worker(counter: ThreadSafeCounter, worker_id: int, iterations: int):
    """Worker function that increments a shared counter."""
    for _ in range(iterations):
        counter.increment()
    print(f"Worker {worker_id} completed")


def main():
    """Demonstrate thread-safe shared state."""
    counter = ThreadSafeCounter()

    with ThreadPoolExecutor(max_workers=4) as executor:
        # Submit worker tasks
        futures = []
        for i in range(4):
            future = executor.submit(worker, counter, i, 1000)
            futures.append(future)

        # Wait for all to complete
        for future in futures:
            future.result()

    print(f"Final counter value: {counter.value}")
    assert counter.value == 4000  # 4 workers * 1000 increments each
```

## Compatibility

Checking dependency compatibility is crucial before enabling free-threaded mode. Incompatibilities typically arise from:

1. **C extensions** that rely on the GIL for internal synchronization
2. **Pure Python modules** with unsynchronized access to shared mutable state
3. **Third-party packages** that haven't been tested or updated for free-threading

### Compatibility Checking Strategy

#### 1. Build and Test in Free-Threaded Mode
The most reliable approach is to build Python 3.14 with `--disable-gil` and run your test suite:

```bash
# Download and build free-threaded Python 3.14
wget https://www.python.org/ftp/python/3.14.0/Python-3.14.0.tgz
tar -xzf Python-3.14.0.tgz
cd Python-3.14.0
./configure --disable-gil --enable-optimizations
make -j$(nproc)
sudo make install

# Create virtual environment with free-threaded python
/path/to/python3.14 -m venv venv_freethread
source venv_freethread/bin/activate

# Install dependencies and run tests
pip install -r requirements.txt
pytest  # or your test runner
```

#### 2. Dependency Analysis Checklist

| Check Type                 | What to Verify                                                                 | Tools/Methods                                                                 |
|----------------------------|-------------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| **C Extensions**           | Are they free-thread safe? Do they use internal GIL-dependent locks?          | Check package documentation, test in free-threaded env, look for Py_GIL_DISABLED macros |
| **Pure Python Modules**    | Do they access shared mutable state without synchronization?                  | Code review, search for global/module-level mutable state, run concurrency tests |
| **Thread Safety**          | Does the code assume GIL-protected operations are atomic?                     | Look for operations like `dict.update()`, `list.append()` on shared objects   |
| **Third-party Packages**   | Are they maintained and free-thread compatible?                               | Check PyPI descriptions, issue trackers, test isolation                       |
| **Internal Code**          | Does your codebase have unsynchronized shared state?                          | Audit using the process_globals.py checker patterns                           |

#### 3. Specific Compatibility Tests

Run these tests in your free-threaded environment:

```python
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
import time


def test_basic_threading():
    """Test that basic threading works."""
    def worker():
        time.sleep(0.01)
        return 1

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker) for _ in range(10)]
        results = [f.result() for f in futures]
    assert sum(results) == 10
    print("✓ Basic threading works")


def test_cpu_bound_parallelism():
    """Test that CPU-bound work actually runs in parallel."""
    import math

    def is_prime(n):
        if n < 2:
            return False
        for i in range(2, int(math.sqrt(n)) + 1):
            if n % i == 0:
                return False
        return True

    # Test with a range that should take measurable time
    numbers = list(range(10000, 10100))  # Numbers to check for primality

    start = time.time()
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(is_prime, numbers))
    parallel_time = time.time() - start

    # Sequential time for comparison
    start = time.time()
    sequential_results = [is_prime(n) for n in numbers]
    sequential_time = time.time() - start

    assert results == sequential_results
    # Should see some speedup (exact ratio depends on system)
    print(f"✓ CPU parallelism: {sequential_time:.2f}s sequential vs {parallel_time:.2f}s parallel")


def test_shared_state_safety():
    """Test that shared state requires explicit synchronization."""
    # UNSAFE version - will likely show race conditions in free-threaded mode
    class UnsafeCounter:
        def __init__(self):
            self.value = 0
        def increment(self):
            self.value += 1  # Not atomic!

    # SAFE version - uses lock
    class SafeCounter:
        def __init__(self):
            self.value = 0
            self._lock = threading.Lock()
        def increment(self):
            with self._lock:
                self.value += 1

    def worker_unsafe(counter):
        for _ in range(100):
            counter.increment()

    def worker_safe(counter):
        for _ in range(100):
            counter.increment()

    # Test unsafe counter (may show incorrect final value)
    unsafe = UnsafeCounter()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker_unsafe, unsafe) for _ in range(4)]
        [f.result() for f in futures]
    # In free-threaded mode, this will likely be < 400 due to race conditions
    print(f"Unsafe counter result: {unsafe.value} (may be < 400 due to races)")

    # Test safe counter
    safe = SafeCounter()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker_safe, safe) for _ in range(4)]
        [f.result() for f in futures]
    assert safe.value == 400  # Should be correct with locking
    print("✓ Safe counter works correctly")


if __name__ == "__main__":
    print(f"Python version: {sys.version}")
    print(f"Free-threaded build: {hasattr(sys, 'getdlopenflags') and bool(sys.getdlopenflags() & 0x10000)}")
    # Note: The actual free-thread detection is more complex; this is illustrative

    test_basic_threading()
    test_cpu_bound_parallelism()
    test_shared_state_safety()
```

### Handling Incompatibilities

When you encounter incompatible dependencies:

1. **Check for updates**: Maintainers may have released free-thread compatible versions
2. **Use isolation**: Run incompatible components in separate processes using `ProcessPoolExecutor`
3. **Fallback to GIL mode**: Use a GIL-enabled Python 3.14 for incompatible workloads
4. **Wrapper approaches**: Create thread-safe wrappers around incompatible C extensions
5. **Process-based alternatives**: Use `InterpreterPoolExecutor` (if subinterpreters work) or `ProcessPoolExecutor`

### Migration Strategy

1. **Start with testing**: Build free-threaded Python and run your test suite
2. **Identify failures**: Note which tests fail and why (look for race conditions, crashes)
3. **Check dependencies**: Test each major dependency in isolation
4. **Fix internal code**: Address any shared state issues in your codebase
5. **Isolate problematic deps**: Use processes for incompatible components
6. **Gradual rollout**: Enable free-threading for compatible services first
7. **Monitor**: Watch for performance regressions or new concurrency bugs in production

## Related Documentation

- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
- Consult `SKILL.md` for high-level skill conventions and recommendations
- Review `process_globals.py` checker for patterns on detecting unsafe shared state
