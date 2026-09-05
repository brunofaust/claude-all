# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces free-threading via PEP 703, which makes the Global Interpreter Lock (GIL) optional. When free-threading is enabled (via the `-X gil=0` flag or PYTHON_GIL=0 environment variable), multiple Python threads can execute Python bytecode simultaneously, providing true parallelism for CPU-bound workloads.

This feature works alongside the existing `InterpreterPoolExecutor` (PEP 734) which provides subinterpreter-based parallelism. Free-threading offers lower overhead than subinterpreters since threads share the same memory space, but requires careful handling of shared mutable state.

In the brunofaust-python-style skill, we continue to use `InterpreterPoolExecutor` for CPU-bound pure Python work and `run_in_thread()` for blocking code, as these patterns provide better isolation and compatibility guarantees. Free-threading is an alternative approach that may be suitable for specific use cases.

## Use Cases

Free-threading is most beneficial for:

- **CPU-bound pure Python computations** where true parallelism can reduce execution time
- **Workloads that can be parallelized without shared mutable state**
- **Applications that currently use threading but are limited by the GIL**
- **Scenarios where the overhead of process-based parallelism (multiprocessing) is prohibitive**

Not suitable for:
- I/O-bound workloads (use async/await or `run_in_thread()` instead)
- Workloads requiring frequent shared state synchronization
- Code that relies on C extensions with incompatible threading behavior

## Pros and Cons

### Advantages

| Benefit | Description |
|---------|-------------|
| True Parallelism | Multiple threads can execute Python bytecode simultaneously when GIL is disabled |
| Lower Overhead | Less memory and startup overhead compared to `ProcessPoolExecutor` |
| Shared Memory | Threads share the same address space, enabling efficient data sharing |
| Familiar API | Uses standard `threading.Thread` API that developers already know |

### Limitations

| Limitation | Description |
|------------|-------------|
| Shared State Risks | Mutable shared data requires explicit synchronization (locks, etc.) |
| Extension Compatibility | C extensions must be updated to work correctly with free-threading |
| Debugging Complexity | Concurrent bugs (race conditions, deadlocks) are harder to diagnose |
| Opt-In Requirement | Requires `-X gil=0` flag or environment variable to enable |
| Not Universally Beneficial | I/O-bound workloads see little improvement; pure Python CPU workloads benefit most |

## Implementation

Free-threading is enabled at interpreter startup and works with standard threading primitives. Here are examples for basic and hybrid workloads:

### Basic CPU-Bound Workload

```python
import threading
import time
from typing import List


def cpu_bound_task(n: int) -> int:
    """CPU-intensive computation: calculate sum of squares."""
    return sum(i * i for i in range(n))


def parallel_free_threaded(numbers: List[int]) -> List[int]:
    """Execute CPU-bound tasks in parallel using free-threading.

    Requires Python 3.14+ with free-threading enabled (-X gil=0).
    """
    results = [None] * len(numbers)

    def worker(idx: int, value: int) -> None:
        results[idx] = cpu_bound_task(value)

    threads = []
    for i, n in enumerate(numbers):
        thread = threading.Thread(target=worker, args=(i, n))
        threads.append(thread)
        thread.start()

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    return results


# Usage (requires free-threading enabled):
# PYTHON_GIL=0 python3 -m myapp
# or
# python3 -X gil=0 myapp.py
if __name__ == "__main__":
    test_data = [100000, 200000, 150000, 300000]
    start = time.time()
    results = parallel_free_threaded(test_data)
    elapsed = time.time() - start
    print(f"Results: {results}")
    print(f"Time elapsed: {elapsed:.2f}s")
```

### Hybrid CPU + I/O Workload

For workloads that combine CPU-intensive processing with I/O operations, we recommend sticking with the established brunofaust-python-style patterns:

```python
import asyncio
from pathlib import Path
from typing import List


async def process_file_cpu_intensive(file_path: Path) -> dict:
    """Process a file with CPU-intensive analysis (suitable for free-threading or InterpreterPoolExecutor)."""
    # CPU-bound work: parse and analyze file contents
    data = await run_in_thread(file_path.read_text)  # I/O offloaded to thread

    # CPU-bound analysis (could use free-threading or InterpreterPoolExecutor)
    analysis_result = await run_in_thread(
        _cpu_bound_analysis, data
    )

    return {
        "file": file_path.name,
        "analysis": analysis_result,
        "size": data.__sizeof__()
    }


def _cpu_bound_analysis(text: str) -> dict:
    """CPU-bound text analysis."""
    lines = text.split('\n')
    words = text.split()
    return {
        "line_count": len(lines),
        "word_count": len(words),
        "char_count": len(text),
        "avg_word_len": sum(len(w) for w in words) / max(len(words), 1)
    }


async def process_files_hybrid(file_paths: List[Path]) -> List[dict]:
    """Process multiple files with hybrid CPU/I/O workload.

    Uses brunofaust-python-style patterns:
    - I/O operations offloaded via run_in_thread()
    - CPU-bound work can use free-threading, InterpreterPoolExecutor, or run_in_thread()
    """
    # For I/O-bound file reading: use run_in_thread() (established pattern)
    # For CPU-bound analysis: could use free-threading if enabled and compatible

    tasks = [process_file_cpu_intensive(fp) for fp in file_paths]
    return await asyncio.gather(*tasks)


# Usage remains the same regardless of threading model:
# asyncio.run(process_files_hybrid(paths))
```

**Note**: In the brunofaust-python-style skill, we recommend continuing to use `InterpreterPoolExecutor` for CPU-bound pure Python work and `run_in_thread()` for blocking code, as these provide better isolation and compatibility. Free-threading is an alternative that may be evaluated on a case-by-case basis.

## Compatibility

Checking dependency compatibility is crucial when considering free-threading. Here's how to evaluate whether your dependencies are compatible:

### Compatibility Checklist

| Check | How to Verify | Action if Incompatible |
|-------|---------------|------------------------|
| **C Extension Thread Safety** | Check if extension releases GIL during blocking operations or uses thread-local state | Use `run_in_thread()` instead of free-threading for blocking operations |
| **Pickle Requirements** | Free-threading doesn't have pickle requirements (unlike InterpreterPoolExecutor) | No special handling needed for data transfer between threads |
| **Shared Mutable State** | Audit code for shared mutable state accessed from multiple threads | Add appropriate synchronization (locks, semaphores) or use thread-local storage |
| **Global Interpreter Lock Dependencies** | Search for code that relies on GIL for atomicity (e.g., `list.append()` assumed atomic) | Replace with explicit synchronization or use thread-safe alternatives |
| **Extension Compatibility Matrix** | Consult extension documentation or test with `-X gil=0` | Use compatibility shims or wait for extension updates |
| **Library-Level Thread Safety** | Check if library documentation specifies thread-safety guarantees | Use library in single-threaded mode or with appropriate locking |

### Dependency Validation Strategies

1. **Runtime Testing**:
   ```bash
   # Test your application with free-threading enabled
   PYTHON_GIL=0 python3 -m pytest tests/
   PYTHON_GIL=0 python3 myapp.py
   ```

2. **Extension-Specific Checks**:
   - For Polars: Check if operations release GIL during execution
   - For DeltaTable: Verify Rust FFI calls are thread-safe
   - For custom C extensions: Audit thread safety of global state

3. **Gradual Adoption**:
   - Enable free-threading for specific modules/services first
   - Use feature flags to toggle free-threading behavior
   - Monitor for race conditions and performance regressions

4. **Fallback Patterns**:
   ```python
   import sys
   from concurrent.futures import InterpreterPoolExecutor
   import threading

   def get_executor():
       """Return appropriate executor based on Python version and capabilities."""
       if hasattr(sys, '_is_gil_enabled') and not sys._is_gil_enabled():
           # Free-threading available - use threading for CPU-bound work
           return threading  # Would return a thread pool wrapper in practice
       elif sys.version_info >= (3, 14):
           # Python 3.14+ but GIL enabled - use InterpreterPoolExecutor
           return InterpreterPoolExecutor
       else:
           # Older Python - use ThreadPoolExecutor for CPU-bound work
           from concurrent.futures import ThreadPoolExecutor
           return ThreadPoolExecutor
   ```

### Project-Specific Guidance

Following brunofaust-python-style conventions:

1. **Continue using `run_in_thread()` for blocking code** (file I/O, C extensions like Polars/DeltaTable) regardless of free-threading availability
2. **For CPU-bound pure Python work**, evaluate free-threading vs `InterpreterPoolExecutor` based on:
   - Performance requirements
   - Dependency compatibility
   - Team familiarity with threading vs subinterpreter models
3. **Never use `asyncio.to_thread` or raw `ThreadPoolExecutor`** - these are banned by project policy
4. **Always follow the project's banned-api rules** and use the sanctioned offloading mechanisms

When in doubt, stick with the established patterns:
- I/O-bound work: `async/await` + `run_in_thread()` for blocking operations
- CPU-bound pure Python: `InterpreterPoolExecutor` (Python 3.14+) or evaluate free-threading
- CPU-bound C extensions: `run_in_thread()` (these already release the GIL effectively)

## Related Documentation

- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
- Consult `SKILL.md` for high-level skill conventions and recommendations
