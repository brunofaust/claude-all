# Free-thread Python 3.14 — reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces free-threaded execution via PEP 734, which adds support for subinterpreters that can run in parallel without the Global Interpreter Lock (GIL) constraint. This is exposed through the `concurrent.futures.InterpreterPoolExecutor` class.

Unlike traditional threading where the GIL prevents true parallelism for CPU-bound tasks, subinterpreters each have their own GIL, allowing genuine parallel execution of Python code. This provides a middle ground between threading (low overhead, shared memory) and multiprocessing (true parallelism, high overhead, separate memory spaces).

The free-threaded execution model relates to the existing `InterpreterPoolExecutor` in that it's the same underlying mechanism — subinterpreters providing true parallelism with lower overhead than process-based approaches.

## Use Cases

Free-threaded execution via `InterpreterPoolExecutor` is beneficial for:

- **CPU-bound pure Python work**: Mathematical computations, data parsing, algorithms that don't rely on shared state
- **Embarrassingly parallel problems**: Tasks that can be divided into independent units of work
- **Scientific computing**: Numerical simulations, statistical analysis, machine learning preprocessing
- **Data transformation pipelines**: Independent transformation steps on data chunks

It is **not** suitable for:
- Tasks requiring shared mutable state between workers
- Work that depends on thread-local storage or global variables
- I/O-bound operations (use `run_in_thread()` instead)
- Work involving C extensions that don't properly release the GIL or use global state

## Pros and Cons

### Advantages

| Benefit | Description |
|---------|-------------|
| **True parallelism** | Each subinterpreter has its own GIL, enabling concurrent execution of Python bytecode |
| **Lower overhead** | Compared to `ProcessPoolExecutor`, subinterpreters share memory space and have faster startup |
| **Memory efficiency** | Objects can be shared between interpreters when using shareable types (limited set) |
| **Faster communication** | Data exchange between interpreters is faster than inter-process communication |
| **Same API** | Follows the familiar `Executor` interface like `ThreadPoolExecutor` and `ProcessPoolExecutor` |

### Limitations

| Limitation | Description |
|------------|-------------|
| **Shared state restrictions** | Interpreters cannot share arbitrary objects; only specific shareable types or picklable data |
| **Pickling requirement** | Most data must be picklable to pass between interpreters |
| **C extension compatibility** | C extensions must properly handle subinterpreter isolation and GIL state |
| **Global state issues** | Module-level globals, singletons, and caches may not work as expected |
| **Debugging complexity** | Traditional debugging tools may not work seamlessly across interpreters |
| **Limited shareable types** | Only `str | bytes | int | float | bool | None | tuple | memoryview` can be shared without pickling |

## Implementation

### Basic Usage

For CPU-bound pure Python tasks that don't require shared state:

```python
from concurrent.futures import InterpreterPoolExecutor
from typing import List


def prime_factors(n: int) -> List[int]:
    """CPU-bound computation: find prime factors of a number."""
    factors = []
    d = 2
    while d * d <= n:
        while n % d == 0:
            factors.append(d)
            n //= d
        d += 1 if d == 2 else 2  # Skip even numbers after 2
    if n > 1:
        factors.append(n)
    return factors


def compute_prime_factors(numbers: List[int]) -> List[List[int]]:
    """Compute prime factors for a list of numbers using free-threaded execution."""
    with InterpreterPoolExecutor() as executor:
        # Map the function across the input data
        results = list(executor.map(prime_factors, numbers))
    return results


# Example usage
if __name__ == "__main__":
    numbers = [2**i - 1 for i in range(10, 20)]  # Mersenne numbers
    results = compute_prime_factors(numbers)
    for num, factors in zip(numbers, results):
        print(f"{num}: {factors}")
```

### Hybrid CPU + I/O Workloads

For workloads that combine CPU-intensive processing with I/O operations, use a hybrid approach:

```python
import asyncio
from concurrent.futures import InterpreterPoolExecutor
from typing import List, Dict
import aiofiles
import json


async def process_data_file(file_path: str) -> Dict[str, float]:
    """Process a single data file: read (I/O), compute (CPU), return results."""
    # I/O-bound operation: read file
    async with aiofiles.open(file_path, 'r') as f:
        content = await f.read()

    # CPU-bound operation: parse and compute statistics
    def compute_stats(text: str) -> Dict[str, float]:
        lines = text.strip().split('\n')
        numbers = [float(line.strip()) for line in lines if line.strip()]
        if not numbers:
            return {"count": 0, "mean": 0.0, "sum": 0.0}

        return {
            "count": len(numbers),
            "sum": sum(numbers),
            "mean": sum(numbers) / len(numbers),
            "min": min(numbers),
            "max": max(numbers)
        }

    # Offload CPU-intensive work to subinterpreters
    with InterpreterPoolExecutor() as executor:
        stats = await asyncio.get_event_loop().run_in_executor(
            executor, compute_stats, content
        )

    return stats


async def process_multiple_files(file_paths: List[str]) -> List[Dict[str, float]]:
    """Process multiple files concurrently using asyncio for I/O and subinterpreters for CPU work."""
    # Create tasks for concurrent file processing
    tasks = [process_data_file(path) for path in file_paths]
    results = await asyncio.gather(*tasks)
    return results


# Example usage
async def main():
    files = [f"data_{i}.txt" for i in range(5)]
    results = await process_multiple_files(files)
    for file_path, stats in zip(files, results):
        print(f"{file_path}: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
```

### Comparison with Existing Patterns

When deciding between free-threaded execution and existing patterns:

| Approach | Best For | Limitations |
|----------|----------|-------------|
| `InterpreterPoolExecutor` (free-threaded) | CPU-bound pure Python, embarrassingly parallel problems | Requires picklable data, no shared mutable state |
| `run_in_thread()` | Blocking I/O, C extensions, shared state needed | Limited by GIL for CPU-bound Python code |
| `asyncio` native | I/O-bound async operations, network calls | Not suitable for CPU-bound work |

## Compatibility

### Dependency Compatibility Checks

To determine if a dependency is compatible with free-threaded execution:

1. **Check if it's pure Python or C extension**:
   - Pure Python modules: Generally compatible if they don't rely on shared global state
   - C extensions: Must be examined for GIL handling and global state usage

2. **Verify pickling compatibility**:
   ```python
   import pickle

   # Test if objects can be pickled (required for InterpreterPoolExecutor)
   try:
       pickled = pickle.dumps(some_object)
       unpickled = pickle.loads(pickled)
       # Compatible if no exception and object behaves correctly
   except (pickle.PicklingError, AttributeError, TypeError):
       # Not compatible with free-threaded execution
       pass
   ```

3. **Check for shared global state**:
   - Look for module-level variables, singletons, global caches
   - These may not work correctly across interpreters
   - Prefer dependency injection or explicit state passing

4. **Examine C extension GIL handling**:
   - Extensions that properly release the GIL during blocking operations may work better with `run_in_thread()`
   - Extensions using Python's C API for object creation/manipulation need subinterpreter awareness

### Strategies for Handling Incompatibilities

| Incompatibility Type | Strategy |
|----------------------|----------|
| **Non-picklable objects** | Convert to picklable format before processing (e.g., dataclasses → dicts, custom objects → tuples/namedtuples) |
| **C extensions with global state** | Use `run_in_thread()` instead of `InterpreterPoolExecutor` for these operations |
| **Shared state requirements** | Redesign to avoid shared state, or use `run_in_thread()` with appropriate locking |
| **Debugging difficulties** | Test with single-threaded execution first, then scale to free-threaded |
| **Performance overhead concerns** | Profile both approaches; free-threaded has lower overhead than processes but higher than threads |

### Decision Flow

When deciding whether to use free-threaded execution for a dependency:

```
Is the workload CPU-bound?
  ↓ No → Consider async I/O or run_in_thread() for blocking operations
  ↓ Yes
    ↓
Is it pure Python code?
  ↓ No (C extension) → Check if extension releases GIL and handles subinterpreters
                      → If yes, try InterpreterPoolExecutor; if no, use run_in_thread()
  ↓ Yes
    ↓
Are data structures picklable or shareable?
  ↓ No → Consider data transformation or use run_in_thread() with careful state management
  ↓ Yes
    ↓
Does code rely on shared global state?
  ↓ Yes → Refactor to eliminate shared state or use run_in_thread()
  ↓ No → Use InterpreterPoolExecutor
```

### Project-Specific Guidelines

Following the patterns established in this codebase:

1. **Prefer `run_in_thread()` for**:
   - File I/O operations
   - Working with Polars, DeltaTable, or other data libraries with C extensions
   - Any operation requiring shared mutable state
   - When working with dependencies known to have subinterpreter compatibility issues

2. **Consider `InterpreterPoolExecutor` for**:
   - Pure Python mathematical computations
   - Data parsing and transformation algorithms
   - Embarrassingly parallel problems with independent data chunks
   - Situations where the lower overhead of subinterpreters vs. processes is beneficial

3. **Always validate compatibility** by:
   - Running tests with both approaches
   - Checking for pickling errors
   - Verifying behavior is consistent between threaded and free-threaded execution
   - Monitoring for unexpected behavior related to global state
