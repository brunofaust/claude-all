# Free-threading in Python 3.14 — Reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces free-threading mode (PEP 703) as an optional build configuration that makes the Global Interpreter Lock (GIL) per-interpreter rather than global. When combined with `InterpreterPoolExecutor` (PEP 734), this enables true parallelism for CPU-bound Python code without the overhead of processes.

In free-threading mode:
- Each subinterpreter has its own GIL
- Multiple interpreters can run Python code in parallel
- Shared mutable state between interpreters is prohibited
- Only picklable objects can be passed between interpreters
- C extensions must be updated to work with per-interpreter GIL

The project uses `InterpreterPoolExecutor` from the standard library for free-threading workloads, which provides a familiar `Executor` interface similar to `ThreadPoolExecutor` and `ProcessPoolExecutor`.

## Use Cases

Free-threading with `InterpreterPoolExecutor` is beneficial for:

| Scenario                              | Description                                                                 |
|---------------------------------------|-----------------------------------------------------------------------------|
| CPU-bound pure Python computation     | Mathematical calculations, data processing, parsing, encoding/decoding      |
| Embarrassingly parallel workloads     | Independent tasks that don't require sharing state during execution         |
| Libraries updated for free-threading  | Pure Python packages that don't rely on shared C extension global state     |
| Hybrid CPU/I/O workloads              | CPU-intensive preparation followed by I/O (use `run_in_thread` for I/O)     |

**Not suitable for:**
- Blocking I/O operations (use `run_in_thread` instead)
- C extensions that haven't been updated for free-threading
- Workloads requiring shared mutable state between workers
- Tasks needing non-picklable arguments or return values

## Pros and Cons

### Advantages
- **True parallelism**: Multiple CPU cores utilized for Python code
- **Lower overhead**: Faster startup and less memory usage than `ProcessPoolExecutor`
- **Familiar API**: Same `Executor` interface as other concurrent.futures executors
- **Better isolation**: No shared memory reduces corruption risks
- **Efficient data sharing**: Pickle-based transfer is often faster than process serialization

### Limitations
- **Shared state prohibited**: Mutable objects cannot be shared between interpreters
- **Pickling requirements**: All arguments and results must be picklable
- **C extension compatibility**: Extensions must support per-interpreter GIL
- **Global state issues**: C extensions with module-level globals may behave unexpectedly
- **Debugging complexity**: Issues may only manifest in multi-interpreter contexts

## Implementation

### Basic CPU-bound Workload

```python
"""
cpu_work.py — Example CPU-bound computation using free-threading.

Demonstrates basic usage of InterpreterPoolExecutor for parallel
mathematical calculations.
"""

from concurrent.futures import InterpreterPoolExecutor
from typing import List


def compute_factorial(n: int) -> int:
    """CPU-bound factorial calculation."""
    if n < 0:
        raise ValueError("Factorial undefined for negative numbers")
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result


def process_numbers(numbers: List[int]) -> List[int]:
    """Process a list of numbers in parallel using free-threading."""
    with InterpreterPoolExecutor() as executor:
        # Map each number to its factorial computation
        results = list(executor.map(compute_factorial, numbers))
    return results


# Example usage
if __name__ == "__main__":
    numbers = [5, 7, 10, 12, 15]
    factorials = process_numbers(numbers)
    print(f"Factorials: {factorials}")
    # Output: Factorials: [120, 5040, 3628800, 479001600, 1307674368000]
```

### Hybrid CPU + I/O Workload

```python
"""
hybrid_work.py — Example hybrid workload combining CPU and I/O.

Shows how to use InterpreterPoolExecutor for CPU-intensive preparation
followed by run_in_thread for blocking I/O operations.
"""

import json
from concurrent.futures import InterpreterPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

from src.claude_all.hooks.python-thread-subprocess-guard import run_in_thread


def prepare_data(raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """CPU-intensive data preparation (free-threading suitable)."""
    prepared = []
    for item in raw_data:
        # Simulate CPU-intensive transformation
        processed = {
            "id": item["id"],
            "normalized_name": item["name"].strip().lower(),
            "value_squared": item["value"] ** 2,
            "category_hash": hash(item["category"]) % 1000,
        }
        prepared.append(processed)
    return prepared


def save_to_file(data: List[Dict[str, Any]], filepath: Path) -> None:
    """Blocking I/O operation - save data as JSON."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps(data, indent=2))


async def process_and_save(
    raw_data: List[Dict[str, Any]], output_path: Path
) -> None:
    """Process data with free-threading then save with thread offload."""
    # CPU-bound preparation with InterpreterPoolExecutor
    with InterpreterPoolExecutor() as executor:
        prepared_data = list(executor.map(prepare_data, [raw_data]))[0]

    # Blocking I/O with run_in_thread (file write)
    await run_in_thread(save_to_file, prepared_data, output_path)


# Example usage in async context
# async def main():
#     data = [
#         {"id": 1, "name": " Alice ", "value": 10, "category": "A"},
#         {"id": 2, "name": " Bob ", "value": 20, "category": "B"},
#     ]
#     await process_and_save(data, Path("output/processed.json"))
```

## Compatibility

### Dependency Compatibility Checks

Before using `InterpreterPoolExecutor`, verify dependencies meet these requirements:

| Check                          | How to Verify                                                                 | Action if Failed                                                                 |
|--------------------------------|-------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| Pure Python vs C extension     | Check if package contains `.so`/`.pyd` files or uses Cython/Rust bindings     | Use `run_in_thread` for C extension-heavy workloads                              |
| GIL release in C extensions    | Verify extension documentation or source for `Py_BEGIN_ALLOW_THREADS`         | Avoid free-threading; use `run_in_thread`                                        |
| Picklable arguments/results    | Test with `pickle.dumps()`/`pickle.loads()` on typical data structures        | Convert to picklable types or use `run_in_thread`                                |
| Shared mutable state           | Review code for module-level globals or class attributes shared between calls | Refactor to avoid shared state or use `run_in_thread`                            |
| Subinterpreter support         | Check if package mentions Python 3.14/free-threading compatibility            | Use `run_in_thread` until compatibility is confirmed                             |

### Strategies for Handling Incompatibilities

1. **Selective Offloading**
   ```python
   # Use free-threading for pure Python parts, threads for C extensions
   def hybrid_process(item):
       cpu_result = pure_python_computation(item)  # InterpreterPoolExecutor
       io_result = blocking_io_operation(cpu_result)  # run_in_thread
       return io_result
   ```

2. **Fallback Mechanism**
   ```python
   def safe_parallel_process(items, func):
       try:
           # Try free-threading first
           with InterpreterPoolExecutor() as executor:
               return list(executor.map(func, items))
       except (TypeError, pickle.PicklingError):
           # Fall back to thread pool for incompatible workloads
           return await run_in_thread_batch(func, items)
   ```

3. **Adapter Pattern for Incompatible Libraries**
   ```python
   # Wrap incompatible C extension library
   def safe_polars_operation(df_query):
       # Polars doesn't support free-threading yet - use thread offload
       return await run_in_thread(lambda: pl.DataFrame(df_query))
   ```

4. **Dependency Version Pinning**
   ```toml
   # In pyproject.toml - only use free-threading compatible versions
   [project.dependencies]
   # Example: hypothetical library that added free-threading support in 2.0
   mylib = {version = ">=2.0", markers = "python_version >= '3.14'"}
   ```

### Project-Specific Guidelines

Following the conventions established in `async-patterns.md`:

- **Use `InterpreterPoolExecutor` for**: CPU-bound pure Python tasks that don't require sharing state
- **Use `run_in_thread` for**: Blocking I/O, C extensions, and tasks requiring shared mutable state
- **Never use**: `asyncio.to_thread` or raw `ThreadPoolExecutor` (banned by project policy)
- **Always validate**: That arguments and return values are picklable before free-threading

The project's thread pool abstraction in `thread_pool.py` provides `run_in_thread()` as the single owner for blocking work, ensuring consistent pool sizing, naming, and leak tracking.
