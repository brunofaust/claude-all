# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview: Free-Threading and the GIL

Python 3.14 introduces an optional **free-threading build** (PEP 703) that removes the Global Interpreter Lock (GIL), allowing multiple threads to execute Python bytecode in parallel. This is distinct from the per-interpreter GIL introduced in Python 3.12 (PEP 684) which enables subinterpreters to run in parallel (each with its own GIL).

In the standard CPython build, the GIL ensures that only one thread executes Python bytecode at a time, preventing true parallelism for CPU-bound Python code. The free-threading build replaces the GIL with finer-grained locking, enabling multiple threads to run Python code simultaneously on multiple cores.

**Relation to InterpreterPoolExecutor**:
The `concurrent.futures.InterpreterPoolExecutor` (PEP 734, available in Python 3.14+) uses subinterpreters (each with its own GIL) to achieve parallelism without shared mutable state. Free-threading, by contrast, allows threads within the *same* interpreter to run in parallel, but requires explicit synchronization for shared mutable state.

## When to Use Free-Threading

Free-threading is beneficial for:
- **CPU-bound pure Python workloads** that cannot be easily offloaded to C extensions (which already release the GIL during blocking operations).
- Scenarios where you want to avoid the memory overhead of `ProcessPoolExecutor` while achieving true parallelism.
- Workloads where threads need to share mutable state (with appropriate synchronization), which is more efficient than pickling data between processes.

**Not recommended for**:
- I/O-bound work (use `async/await` + `run_in_thread()` for blocking operations).
- Pure Python computations that complete in under ~1ms (threading overhead outweighs benefits).
- Situations where thread-safety cannot be ensured (prefer `ProcessPoolExecutor` or `InterpreterPoolExecutor` for isolation).

## Pros and Cons

### Pros
- **True parallelism for Python code**: Multiple threads can execute Python bytecode simultaneously on multiple cores.
- **Lower memory overhead**: Compared to `ProcessPoolExecutor`, threads share the same memory space.
- **Easier sharing of mutable state**: Objects can be shared between threads without pickling/IPC (though synchronization is required).
- **Compatibility with existing threading code**: Standard `threading` module and `ThreadPoolExecutor` work as expected.

### Cons
- **Requires free-threading build**: Only available in Python 3.14 interpreters compiled with the `--disable-gil` flag.
- **Increased need for thread-safety**: Removing the GIL exposes data races in code that previously relied on the GIL for implicit synchronization.
- **C extension compatibility**: Some C extensions may not be thread-safe in a free-threading environment if they rely on the GIL for internal synchronization.
- **Performance overhead**: Fine-grained locking may slightly increase overhead for single-threaded workloads compared to the GIL.

## Implementation

### Basic CPU-Bound Parallelism

Use `ThreadPoolExecutor` (or `run_in_thread()` from the skill's utilities) to parallelize CPU-bound pure Python functions. Ensure shared mutable state is protected with locks.

```python
"""
cpu_bound.py — Example of CPU-bound parallelism with free-threading.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List


# Shared counter requiring synchronization
counter = 0
counter_lock = threading.Lock()


def increment_counter(times: int) -> None:
    """CPU-bound workload: increment a shared counter."""
    global counter
    local_count = 0
    for _ in range(times):
        local_count += 1  # Pure Python computation
    with counter_lock:
        counter += local_count


def main() -> None:
    global counter
    counter = 0
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Submit 10 tasks, each incrementing 100,000 times
        futures = [executor.submit(increment_counter, 100_000) for _ in range(10)]
        # Wait for all tasks to complete
        for future in futures:
            future.result()
    print(f"Final counter value: {counter}")  # Expected: 1,000,000


if __name__ == "__main__":
    main()
```

### Hybrid CPU and I/O Workloads

For workloads combining CPU-bound pure Python with I/O operations (e.g., reading files, network requests), use `run_in_thread()` to offload blocking operations to a thread pool. The free-threading build allows the CPU-bound portions to run in parallel.

```python
"""
hybrid.py — Example hybrid workload using run_in_thread().
"""
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List

# Assuming run_in_thread is available from the skill's thread utilities
# For demonstration, we define a simplified version here
async def run_in_thread(func, *args):
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor() as pool:
        return await loop.run_in_executor(pool, func, *args)


def cpu_intensive_task(data: List[float]) -> float:
    """CPU-bound pure Python computation."""
    return sum(x * x for x in data)


async def io_bound_task(task_id: int) -> str:
    """Simulate I/O-bound work (e.g., network request)."""
    await asyncio.sleep(0.1)  # Non-blocking sleep
    return f"Task {task_id} completed"


async def process_item(item_id: int, data: List[float]) -> dict:
    """Process one item with both CPU and I/O components."""
    # CPU-bound work runs in a thread (benefits from free-threading parallelism)
    cpu_result = await run_in_thread(cpu_intensive_task, data)
    # I/O-bound work uses async/await (does not block the event loop)
    io_result = await io_bound_task(item_id)
    return {
        "item_id": item_id,
        "cpu_result": cpu_result,
        "io_result": io_result,
    }


async def main() -> None:
    """Process multiple items concurrently."""
    data = [float(i) for i in range(1000)]
    # Process 5 items concurrently
    tasks = [process_item(i, data) for i in range(5)]
    results = await asyncio.gather(*tasks)
    for result in results:
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
```

## Dependency Compatibility

To ensure your dependencies work correctly with Python 3.14 free-threading:

### 1. Check for Pure Python vs. C Extensions
- **Pure Python modules**: Generally thread-safe in free-threading if they do not share mutable state without synchronization. Audit for shared globals or class variables.
- **C extensions**: Must be explicitly tested for thread-safety. Extensions that release the GIL during blocking operations (e.g., NumPy, Pandas for some operations) are safer. Extensions that hold the GIL for internal state may require updates.

### 2. Audit Shared Mutable State
Identify any module-level or class-level mutable state that could be accessed by multiple threads:
```python
# UNSAFE: Shared state without synchronization
shared_cache = {}

def get_value(key):
    return shared_cache.get(key)  # Race condition if another thread sets it

# SAFE: Use threading.Lock or similar
import threading
cache_lock = threading.Lock()
shared_cache = {}

def get_value(key):
    with cache_lock:
        return shared_cache.get(key)
```

### 3. Test with the Free-Threading Build
- Install Python 3.14 free-threading build (e.g., from `python.org` or via `pyenv`).
- Run your test suite to detect failures or hangs.
- Use stress tests with high thread counts to increase likelihood of catching race conditions.

### 4. Consult Documentation and Banned-API Rules
- Refer to `enforcement.md` for any banned-api rules related to threading mechanisms.
- Check third-party documentation for free-threading compatibility statements.
- The skill's `checkers/` directory may include heuristics for thread-unsafe patterns (review manually).

### 5. Gradual Adoption
- Enable free-threading in a staging environment first.
- Monitor for performance regressions or correctness issues.
- Consider using feature flags to toggle free-threading usage based on interpreter capabilities.

## Related Documentation

- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines.
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms.
- Consult `SKILL.md` for high-level skill conventions and recommendations.
