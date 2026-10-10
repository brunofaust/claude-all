# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview: Free-Thread Execution & Relation to GIL and InterpreterPoolExecutor

Python 3.14 introduces **free-threading** builds (via the `--disable-gil` flag) that remove the Global Interpreter Lock (GIL), allowing true parallelism across multiple threads for CPU-bound Python code. This is a significant change from the traditional GIL-limited threading model.

Key points:
- **GIL Removal**: In free-threading mode, Python threads can run in parallel on multiple CPU cores without GIL contention.
- **Relation to InterpreterPoolExecutor**: The `concurrent.futures.InterpreterPoolExecutor` (PEP 734) uses subinterpreters to achieve parallelism with separate GILs per interpreter. Free-threading goes further by removing the GIL entirely within a single interpreter.
- **Compatibility Note**: Free-threading requires a special Python build (`python.exe` or `python` binary compiled with `--disable-gil`). The standard Python 3.14 distribution does **not** include free-threading support; you must obtain or build a free-threading variant.

## When to Use Free-Threading

- **CPU-bound pure Python workloads** that can be parallelized across threads (e.g., numerical computations, data processing, simulations).
- **Workloads where shared mutable state is minimized or eliminated** — free-threading threads share memory, so synchronization is still required for mutable data.
- **Scenarios where the overhead of process-based parallelism (e.g., `ProcessPoolExecutor`) is too high** — free-threading avoids pickle serialization and inter-process communication (IPC) costs.

**Do not use free-threading for**:
- I/O-bound work (use `async/await` + `run_in_thread()` for blocking operations).
- Workloads requiring extensive shared mutable state without proper synchronization (race conditions will occur).
- Environments where dependencies are not free-threading compatible (see Compatibility section).

## Pros and Cons

### Pros
- **True parallelism** for CPU-bound Python code without GIL limitations.
- **Lower overhead** than process-based parallelism (no pickle/IPC).
- **Shared memory space** — easy to share data between threads (with proper synchronization).
- **Compatible with existing threading APIs** (`threading.Thread`, `ThreadPoolExecutor`, etc.) when using a free-threading build.

### Cons
- **Requires special Python build** — not available in standard distributions.
- **Shared mutable state requires explicit synchronization** (locks, semaphores, etc.) to avoid race conditions.
- **Extension modules must be free-threading compatible** — many C extensions may not yet support free-threading.
- **Debugging complexity** — concurrent bugs (race conditions, deadlocks) are more likely and harder to diagnose.
- **Not all Python implementations support it** (e.g., PyPy may have different approaches).

## Implementation

Free-threading uses the same threading APIs as traditional Python, but the underlying behavior changes when running with a free-threading interpreter.

### Basic Usage: CPU-bound Parallel Work

```python
import threading
from concurrent.futures import ThreadPoolExecutor
import time

def cpu_bound_work(n: int) -> int:
    """Example CPU-bound function (e.g., numerical computation)."""
    total = 0
    for i in range(n):
        total += i * i
    return total

def parallel_computation() -> list[int]:
    """Run CPU-bound work in parallel using free-threading."""
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Submit multiple CPU-bound tasks
        futures = [executor.submit(cpu_bound_work, 1000000) for _ in range(8)]
        results = [f.result() for f in futures]
    return results

# In a free-threading Python 3.14 build, the above will run in parallel across cores.
```

### Hybrid Workload: CPU + I/O

For applications mixing CPU-bound and I/O-bound work, combine free-threading with async patterns:

```python
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

# Global thread pool for CPU-bound work (use free-threading build)
CPU_THREADPOOL: ThreadPoolExecutor = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="cpu-pool"
)

async def process_data_item(data: Any) -> Any:
    """Process a single data item with mixed CPU/I/O work."""
    # Step 1: CPU-bound preparation (runs in thread pool)
    prepared = await asyncio.get_running_loop().run_in_executor(
        CPU_THREADPOOL,
        cpu_bound_preparation,
        data
    )

    # Step 2: I/O-bound operation (stays async)
    result = await io_bound_operation(prepared)

    # Step 3: CPU-bound finalization (runs in thread pool)
    finalized = await asyncio.get_running_loop().run_in_executor(
        CPU_THREADPOOL,
        cpu_bound_finalization,
        result
    )

    return finalized

def cpu_bound_preparation(data: Any) -> Any:
    """CPU-bound data preparation."""
    # Simulate CPU-intensive work
    return data  # placeholder

async def io_bound_operation(prepared: Any) -> Any:
    """Async I/O operation (e.g., network request, file read)."""
    # Placeholder for actual async I/O
    await asyncio.sleep(0.1)  # simulate async delay
    return processed_data

def cpu_bound_finalization(result: Any) -> Any:
    """CPU-bound finalization."""
    # Simulate CPU-intensive work
    return result  # placeholder

async def main() -> None:
    """Process multiple data items concurrently."""
    data_items = [f"item_{i}" for i in range(20)]
    tasks = [process_data_item(item) for item in data_items]
    await asyncio.gather(*tasks)
```

**Note**: In a free-threading build, the `ThreadPoolExecutor` will utilize multiple CPU cores for the CPU-bound portions, while the async I/O operations continue to run concurrently on the main event loop.

### Comparison with Existing Patterns

| Pattern                          | Use Case                              | Free-Threading Replacement?       |
|----------------------------------|---------------------------------------|-----------------------------------|
| `asyncio.to_thread()` / `run_in_thread()` | Blocking I/O, C extensions           | ❌ Still preferred for I/O/C-ext   |
| `ThreadPoolExecutor`             | CPU-bound pure Python (GIL-limited)   | ✅ Use with free-threading build   |
| `ProcessPoolExecutor`            | CPU-bound pure Python (process-based) | ⚠️ Only if pickle overhead acceptable |
| `InterpreterPoolExecutor`        | CPU-bound pure Python (subinterpreters)| ⚠️ Alternative; free-threading may be lower overhead |

## Compatibility: Checking Dependencies

Free-threading compatibility requires verifying that your dependencies work correctly in a free-threading environment. Key areas to check:

### 1. Python Version & Build
- Confirm you are using a Python 3.14 interpreter built with `--disable-gil`.
- Check `sysconfig` or platform tags for free-threading indicators:
  ```python
  import sysconfig
  if "free_threading" in sysconfig.get_config_var("PYTHONFRAMEWORK"):
      # Running in free-threading mode
  ```

### 2. Standard Library Modules
Most standard library modules are free-threading safe, but verify:
- `threading`, `concurrent.futures`: Fully supported.
- `multiprocessing`: Unaffected (uses processes, not threads).
- `asyncio`: Works normally; event loop runs in main thread.

### 3. Third-Party Dependencies
Check each dependency for free-threading compatibility:
- **Pure Python modules**: Almost always compatible.
- **C extensions / Cython modules**: Must be compiled and tested for free-threading.
  - Look for wheels or source distributions labeled `free_threading` or `disabled_gil`.
  - Check project documentation or PyPI classifiers for free-threading support.
  - Test in isolated environment before full adoption.

### 4. Internal Modules
Audit your own code for:
- **Shared mutable state**: Protect with locks (`threading.Lock`, `threading.RLock`) or use thread-safe data structures.
- **Global interpreter state**: Avoid modifying global C extension state from multiple threads.
- **Assumptions about GIL**: Remove any code that relies on GIL-induced atomicity (e.g., assuming `list.append()` is thread-safe without locks).

### 5. Compatibility Testing Strategy
1. **Isolate testing**: Create a virtual environment with a free-threading Python build.
2. **Install dependencies**: Attempt to install your project's dependencies.
3. **Run test suite**: Execute your full test suite to catch threading-related failures.
4. **Stress test**: Run concurrent workloads to identify race conditions or deadlocks.
5. **Monitor for segfaults**: Incompatible C extensions may cause crashes.

### 6. Dependency Checklist
When evaluating a dependency for free-threading use:
- [ ] Is it pure Python? (If yes, likely compatible)
- [ ] If it contains C extensions:
    - [ ] Does it provide free-threading wheels?
    - [ ] Is the source compatible with `--disable-gil` compilation?
    - [ ] Has it been tested with free-threading Python?
- [ ] Does it use threading internally? (Check for proper locking)
- [ ] Are there any known issues reported in the project's issue tracker?

### 7. Recommended Tools for Compatibility Checking
- `pip list --format=freeze` to record dependencies.
- `cythonize` with appropriate flags if building from source.
- `auditwheel` or `delvewheel` for inspecting existing wheels (Linux/Windows).
- Custom test scripts that spawn multiple threads and stress the dependency.

## Advanced Scenarios

### Mixed Free-Thread and Async Patterns
Advanced applications might freely mix free-threading threads for CPU work with asyncio for I/O, requiring careful coordination:
- Use `asyncio.run_coroutine_threadsafe()` to schedule coroutines from free-threading threads.
- Use `loop.call_soon_threadsafe()` for thread-safe event loop interactions.
- Avoid blocking the event loop with long-running CPU tasks — offload to thread pool.

### Debugging Complex Concurrency Issues
Free-threading introduces classic shared-memory concurrency challenges:
- **Race conditions**: Use threading locks, semaphores, or condition variables.
- **Deadlocks**: enforce lock ordering, use timeouts on lock acquisition.
- **Starvation**: ensure fair locking policies or use threading barriers.
- **Tools**: Use `faulthandler`, `threading.settrace()`, or external debuggers like `gdb` with Python support.

## Monitoring

Integrate with performance monitoring to track free-threading execution impact:
- **CPU utilization**: Monitor core usage to confirm parallelism is effective.
- **Thread pool metrics**: Track queue depth, wait times, and rejection rates.
- **Application-level metrics**: Measure throughput and latency before/after enabling free-threading.
- **Profiling**: Use `cProfile` with threading support or `py-spy` to analyze concurrent performance.

## Related Documentation

- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines.
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms.
- Consult `SKILL.md` for high-level skill conventions and recommendations.
