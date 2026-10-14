# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces an experimental free-threading build (PEP 703) that makes the Global Interpreter Lock (GIL) optional, allowing true parallelism in Python code. When the GIL is disabled via the `PYTHON_GIL=0` environment variable or build configuration, multiple Python threads can execute bytecode concurrently on multiple CPU cores.

This feature relates to existing concurrency mechanisms in the skill:
- **vs. InterpreterPoolExecutor** (PEP 734): Free-threading shares memory space (requiring explicit synchronization) while interpreters are isolated
- **vs. run_in_thread()**: Free-threading avoids thread-offload overhead but requires thread-safe code
- **Traditional threading**: Previously limited by the GIL for CPU-bound work

The free-threading build is primarily beneficial for **CPU-bound pure Python workloads** that can utilize multiple cores without the GIL bottleneck.

## When to Use

- **CPU-bound pure Python computations** (data processing, numerical simulations, algorithms)
- **Workloads demonstrating scalability** with additional CPU cores in free-threading mode
- **Applications where thread synchronization overhead** is lower than process/interpreter communication costs
- **Hybrid workloads** combining CPU-bound parallelism with I/O-bound async operations

Avoid free-threading for:
- **I/O-bound work** (better served by `async/await` + `run_in_thread()`)
- **Code with complex shared mutable state** that's difficult to make thread-safe
- **Dependencies with C extensions** that may not be free-threading compatible
- **Short-lived computations** where thread creation overhead dominates

## Pros and Cons

### Advantages
- **True parallelism** for CPU-bound pure Python (no GIL bottleneck)
- **Lower overhead** than process-based multiprocessing (shared memory space)
- **Familiar threading model** vs. learning new paradigms
- **Compatible with existing async patterns** for I/O-bound work
- **Gradual adoption** possible per-module or per-function

### Disadvantages
- **Requires thread-safe code** (explicit locking for shared mutable state)
- **Dependency compatibility concerns** (C extensions, third-party packages)
- **Increased debugging complexity** (race conditions, deadlocks)
- **Memory usage considerations** (no process isolation)
- **Experimental status** in Python 3.14 (may change in future versions)

### Comparison with Existing Approaches

| Approach                     | Best For                          | Overhead | Sharing Model      | GIL Impact          |
|------------------------------|-----------------------------------|----------|--------------------|---------------------|
| Free-threading (GIL disabled)| CPU-bound pure Python             | Low      | Shared memory      | Optional            |
| InterpreterPoolExecutor      | CPU-bound pure Python (isolated)  | Medium   | Message passing    | Per-interpreter     |
| run_in_thread()              | Blocking I/O, C extensions        | Medium   | Shared memory      | Per-thread          |
| Traditional threading        | Limited by GIL for CPU work       | Low      | Shared memory      | Always enabled      |
| Async/await                  | I/O-bound, network operations     | Very low | Single-threaded    | N/A                 |

## Implementation

### Enabling Free-Threading

To use free-threading, install and run with the experimental free-threading build:

```bash
# Install free-threading Python 3.14
# (Available via specialty distributors or custom builds)

# Run with GIL disabled
PYTHON_GIL=0 python3.14 myapp.py

# Or check if running in free-threading mode
import sys
if hasattr(sys, 'is_finalizing') and sys._is_gil_enabled() == False:
    print("Running in free-threading mode")
```

### Basic CPU-Bound Parallelism

For CPU-bound pure Python functions, use `concurrent.futures.ThreadPoolExecutor` directly:

```python
"""
cpu_parallel.py — CPU-bound parallelism with free-threading.

Example: Parallel numerical integration using free-threading.
"""

import math
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List


def integrate_segment(f, a: float, b: float, n_segments: int) -> float:
    """Compute definite integral using Simpson's rule (CPU-bound pure Python)."""
    if n_segments < 2 or n_segments % 2 == 1:
        n_segments += 1  # Ensure even

    h = (b - a) / n_segments
    x = a
    total = f(a) + f(b)

    for i in range(1, n_segments):
        x += h
        weight = 4 if i % 2 == 1 else 2
        total += weight * f(x)

    return total * h / 3


def parallel_integrate(f, a: float, b: float, n_workers: int = 4) -> float:
    """Parallelize integration across workers using free-threading."""
    # Split range into equal segments
    worker_range = (b - a) / n_workers

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = []
        for i in range(n_workers):
            worker_a = a + i * worker_range
            worker_b = worker_a + worker_range
            # Each worker computes its segment
            future = executor.submit(integrate_segment, f, worker_a, worker_b, 10000)
            futures.append(future)

        # Sum results from all workers
        total = sum(future.result() for future in futures)

    return total


# Example usage
if __name__ == "__main__":
    # Compute integral of sin(x) from 0 to pi
    result = parallel_integrate(math.sin, 0, math.pi)
    print(f"Integral of sin(x) from 0 to pi: {result:.10f}")
    print(f"Expected: {2.0:.10f}")
```

### Hybrid CPU/I/O Workloads

For applications combining CPU-bound parallelism with I/O-bound async operations:

```python
"""
hybrid.py — Combining free-threading CPU work with async I/O.

Example: Parallel data processing with async file I/O.
"""

import asyncio
import json
import math
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict
import aiofiles


def process_data_chunk(data: List[float]) -> Dict[str, float]:
    """CPU-bound data processing (suitable for free-threading)."""
    if not data:
        return {}

    # Compute statistics (CPU-intensive pure Python)
    n = len(data)
    mean = sum(data) / n
    variance = sum((x - mean) ** 2 for x in data) / n
    std_dev = math.sqrt(variance)

    return {
        "count": n,
        "sum": sum(data),
        "mean": mean,
        "std_dev": std_dev,
        "min": min(data),
        "max": max(data)
    }


async def read_data_file(filepath: str) -> List[float]:
    """Async I/O-bound file reading."""
    async with aiofiles.open(filepath, 'r') as f:
        content = await f.read()
        return [float(line.strip()) for line in content.splitlines() if line.strip()]


async def write_results_file(filepath: str, results: List[Dict]) -> None:
    """Async I/O-bound file writing."""
    async with aiofiles.open(filepath, 'w') as f:
        await f.write(json.dumps(results, indent=2))


async def process_files_parallel(filepaths: List[str]) -> List[Dict]:
    """Process multiple files: async I/O + free-threading CPU work."""
    # Read all files concurrently (I/O-bound)
    read_tasks = [read_data_file(fp) for fp in filepaths]
    data_lists = await asyncio.gather(*read_tasks)

    # Process data in parallel using free-threading (CPU-bound)
    with ThreadPoolExecutor(max_workers=len(data_lists)) as executor:
        process_futures = [
            executor.submit(process_data_chunk, data)
            for data in data_lists
        ]
        results = [future.result() for future in process_futures]

    # Write results concurrently (I/O-bound)
    write_tasks = [
        write_results_file(f"out_{fp}", result)
        for fp, result in zip(filepaths, results)
    ]
    await asyncio.gather(*write_tasks)

    return results


# Example usage
async def main():
    filepaths = ["data1.txt", "data2.txt", "data3.txt"]
    results = await process_files_parallel(filepaths)
    print(f"Processed {len(results)} files")


if __name__ == "__main__":
    # Run with free-threading: PYTHON_GIL=0 python3.14 hybrid.py
    asyncio.run(main())
```

### Thread Safety Requirements

Free-threading requires explicit synchronization for shared mutable state:

```python
"""
thread_safety.py — Thread-safe patterns for free-threading.

Examples: Proper synchronization techniques.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List


# ❌ UNSAFE: Shared mutable state without protection
class UnsafeCounter:
    def __init__(self):
        self.count = 0

    def increment(self):
        # Race condition possible here
        self.count += 1


# ✅ SAFE: Using locks for shared state
class SafeCounter:
    def __init__(self):
        self._count = 0
        self._lock = threading.Lock()

    def increment(self):
        with self._lock:
            self._count += 1

    @property
    def count(self):
        with self._lock:
            return self._count


# ✅ SAFE: Using thread-local storage for per-thread state
def worker_with_local_state(data: List[int]) -> int:
    """Each thread maintains its own state."""
    # Thread-local storage for accumulation
    local_sum = 0
    for value in data:
        local_sum += value * value  # CPU-bound work
    return local_sum


def parallel_sum_of_squares(data_chunks: List[List[int]]) -> int:
    """Parallel sum of squares using thread-local accumulation."""
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(worker_with_local_state, chunk)
            for chunk in data_chunks
        ]
        # Combine results (this part needs synchronization)
        total = sum(future.result() for future in futures)
    return total


# ✅ SAFE: Using atomic operations for simple cases (Python 3.14+)
# Note: For complex operations, locks are still required
from threading import Atomic


class AtomicCounter:
    def __init__(self):
        self._atomic = Atomic(0)

    def increment(self):
        self._atomic.value += 1  # Atomic operation

    @property
    def count(self):
        return self._atomic.value
```

## Dependency Compatibility

Checking dependencies for free-threading compatibility requires auditing for thread safety and C extension behavior.

### Compatibility Categories

1. **Pure Python modules** ✅
   - Generally compatible if already thread-safe
   - Audit for shared mutable state (global variables, class attributes)

2. **C extensions** ⚠️
   - Must release GIL during blocking operations (like traditional threading)
   - Extensions using global state may behave unexpectedly
   - Check documentation for "free-threading" or "GIL-independent" claims

3. **Third-party packages** 🔍
   - Look for explicit free-threading support statements
   - Test in isolated environment before production use
   - Prefer packages with minimal global state

### Compatibility Checking Strategy

#### 1. Runtime Verification

```python
"""
compatibility_check.py — Runtime compatibility verification.
"""

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor


def check_gil_status() -> bool:
    """Check if running with GIL disabled."""
    if hasattr(sys, '_is_gil_enabled'):
        return not sys._is_gil_enabled()
    return False  # Assume GIL enabled if attribute missing


def test_basic_thread_safety() -> bool:
    """Test basic thread safety with shared counter."""
    counter = [0]  # List for mutable reference
    lock = threading.Lock()
    iterations = 10000

    def worker():
        for _ in range(iterations):
            with lock:  # With lock - should be safe
                counter[0] += 1

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker) for _ in range(4)]
        for future in futures:
            future.result()

    expected = 4 * iterations
    return counter[0] == expected


def test_extension_compatibility(extension_func) -> bool:
    """Test if a C extension function behaves correctly."""
    # Call extension function from multiple threads
    results = []

    def worker():
        try:
            result = extension_func()
            results.append(result)
            return True
        except Exception as e:
            print(f"Extension error: {e}")
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        success = all(future.result() for future in futures)

    # Additional validation would be extension-specific
    return success


# Example usage
if __name__ == "__main__":
    if check_gil_status():
        print("Running in free-threading mode")
        if test_basic_thread_safety():
            print("Basic thread safety: PASS")
        else:
            print("Basic thread safety: FAIL")
    else:
        print("Running with GIL enabled (free-threading not active)")
```

#### 2. Dependency Audit Checklist

When evaluating a dependency for free-threading compatibility:

- [ ] **Pure Python**: Review source for global/shared state
- [ ] **C extensions**:
  - Check if documentation mentions free-threading/GIL-0 support
  - Verify extension releases GIL during blocking operations (look for `Py_BEGIN_ALLOW_THREADS`)
  - Test for global state usage that could cause race conditions
- [ ] **Third-party packages**:
  - Look for "free-threading", "PEP 703", or "GIL-free" in documentation
  - Check issue tracker for threading-related problems
  - Consider maintaining a compatibility matrix in your project
- [ ] **Internal modules**: Apply same audit standards as dependencies

#### 3. Testing Recommendations

- **Run test suite** with `PYTHON_GIL=0` to catch threading issues
- **Stress test** with increased thread counts and iterations
- **Use race condition detectors** like `threading` inspection or specialized tools
- **Monitor for deadlocks** and performance anomalies
- **Test edge cases** like exception handling in threaded contexts

### Known Incompatibility Patterns

Avoid or carefully vet dependencies exhibiting:
- **Global caches** without locking (e.g., `lru_cache` on module-level functions)
- **Singleton patterns** using module-level instances
- **C extensions with static/global state** (common in older libraries)
- **Frameworks assuming single-threaded execution** (some GUI or web frameworks)
- **Debugging/profiling tools** that may not support free-threading builds

## Related Documentation

- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
- Consult `SKILL.md` for high-level skill conventions and recommendations
- Review `project-structure.md` for organization of CPU-bound vs I/O-bound components
