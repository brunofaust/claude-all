# Free-Thread Python 3.14 — Reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces free-threading via PEP 734, which provides the `InterpreterPoolExecutor` for true parallelism without the Global Interpreter Lock (GIL) limitations. This feature allows multiple Python interpreters to run concurrently, each with its own GIL, enabling genuine parallel execution of CPU-bound Python code.

Free-threading builds upon the `concurrent.futures` interface familiar from `ThreadPoolExecutor` and `ProcessPoolExecutor`, but instead of using threads or processes, it utilizes subinterpreters. Each subinterpreter has isolated state but can communicate through well-defined channels, primarily by passing picklable objects.

## Use Cases

Free-threading via `InterpreterPoolExecutor` is ideal for:

| Scenario                                | Description                                              |
| --------------------------------------- | -------------------------------------------------------- |
| CPU-bound pure Python workloads         | Mathematical computations, data parsing, text processing |
| Embarrassingly parallel problems        | Monte Carlo simulations, parameter sweeps, batch processing |
| Algorithms requiring true parallelism   | When GIL would significantly limit performance           |
| Lower-overhead alternative to processes | When process creation overhead is prohibitive            |

## Pros and Cons

### Advantages

| Benefit                      | Description                                                                 |
| ---------------------------- | --------------------------------------------------------------------------- |
| True parallelism             | Multiple CPU cores utilized simultaneously for Python code                  |
| Lower overhead               | Faster startup and less memory usage compared to `ProcessPoolExecutor`      |
| Familiar API                 | Same interface as `ThreadPoolExecutor`/`ProcessPoolExecutor`                |
| No GIL contention            | Eliminates the primary bottleneck for CPU-bound Python workloads            |

### Limitations

| Limitation                   | Description                                                                 |
| ---------------------------- | --------------------------------------------------------------------------- |
| Pickling requirement         | Only picklable objects can be passed between interpreters                   |
| No shared mutable state      | Interpreters cannot directly share mutable objects                          |
| C extension compatibility    | Extensions must be subinterpreter-compatible or release the GIL appropriately |
| Debugging complexity         | More complex debugging experience due to isolated interpreter states        |

## Implementation

### Basic Usage

For CPU-bound pure Python computations that don't require shared state:

```python
from concurrent.futures import InterpreterPoolExecutor
from typing import List


def prime_factors(n: int) -> List[int]:
    """Compute prime factors of a number - CPU-bound pure Python."""
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


def process_numbers(numbers: List[int]) -> List[List[int]]:
    """Process a list of numbers in parallel using InterpreterPoolExecutor."""
    with InterpreterPoolExecutor() as executor:
        # Map each number to the prime_factors function
        results = list(executor.map(prime_factors, numbers))
    return results


# Example usage
if __name__ == "__main__":
    numbers = [1234567, 23456789, 345678901, 456789012, 567890123]
    results = process_numbers(numbers)
    for num, factors in zip(numbers, results):
        print(f"{num}: {factors}")
```

### Hybrid CPU + I/O Workloads

For workloads that combine CPU-bound processing with I/O operations, use a hybrid approach:

```python
import json
from concurrent.futures import InterpreterPoolExecutor
from pathlib import Path
from typing import Dict, Any


def parse_json_file(file_path: Path) -> Dict[str, Any]:
    """CPU-bound JSON parsing (pure Python work suitable for InterpreterPoolExecutor)."""
    return json.loads(file_path.read_text())


def save_processed_data(data: Dict[str, Any], output_path: Path) -> None:
    """I/O-bound work better suited for run_in_thread."""
    output_path.write_text(json.dumps(data, indent=2))


async def process_json_files(file_paths: list[Path]) -> None:
    """Process multiple JSON files with hybrid approach."""
    # CPU-bound parsing with InterpreterPoolExecutor
    with InterpreterPoolExecutor() as executor:
        parsed_data = list(executor.map(parse_json_file, file_paths))

    # I/O-bound saving with run_in_thread (assuming run_in_thread is available)
    # In practice, you would use the project's run_in_thread utility
    save_tasks = []
    for i, data in enumerate(parsed_data):
        output_path = file_paths[i].with_suffix('.processed.json')
        # This would be replaced with actual run_in_thread call
        save_tasks.append(save_processed_data(data, output_path))

    # Execute I/O operations (simplified example)
    for task in save_tasks:
        task


# Usage would be: await process_json_files(list_of_paths)
```

## Compatibility

### Dependency Compatibility Checklist

To determine if a dependency is compatible with `InterpreterPoolExecutor`, evaluate:

| Check                                     | How to Verify                                                                 | Recommended Action if Failed                          |
| ----------------------------------------- | ----------------------------------------------------------------------------- | ----------------------------------------------------- |
| **C extension GIL behavior**              | Check if extension releases GIL during long operations                        | Use `run_in_thread()` instead                         |
| **Object picklability**                   | Verify arguments/return values are picklable with `pickle` or `cloudpickle`   | Convert to picklable format or use `run_in_thread()`  |
| **Shared mutable state**                  | Determine if extension relies on global/static variables                      | Avoid sharing state or use `run_in_thread()`          |
| **Subinterpreter support**                | Check if extension is compatible with multiple interpreters                   | Consult extension documentation                       |
| **Thread safety**                         | Ensure extension is safe for concurrent use                                   | May require additional synchronization                |

### Strategies for Handling Incompatibilities

1. **Selective Offloading**
   ```python
   # Use InterpreterPoolExecutor for compatible pure Python work
   # Use run_in_thread() for incompatible C extensions
   ```

2. **Data Format Conversion**
   - Convert complex objects to picklable formats (JSON, protobuf) before passing to interpreters
   - Reconstruct objects after receiving results

3. **Fallback Mechanisms**
   ```python
   try:
       with InterpreterPoolExecutor() as executor:
           return list(executor.map(cpu_bound_func, items))
   except (pickle.PicklingError, TypeError):
       # Fallback to thread pool for incompatible workloads
       return await run_in_thread_pool(cpu_bound_func, items)
   ```

4. **Extension-Specific Solutions**
   - Some libraries provide explicit subinterpreter support
   - Others may require specific initialization patterns

### Project-Specific Guidance

Following the conventions established in this skill:

- **Prefer `InterpreterPoolExecutor`** for CPU-bound pure Python workloads (parsing, mathematical computations, data transformation)
- **Continue using `run_in_thread()`** for:
  - Blocking I/O operations (file, network)
  - C extensions that don't release the GIL (Polars, NumPy in some operations)
  - Workloads requiring shared mutable state
  - When compatibility with subinterpreters cannot be verified

The `async-patterns.md` reference provides detailed guidance on choosing between these approaches based on workload characteristics.

## Relationship with Existing Documentation

This file complements the `InterpreterPoolExecutor` section in `async-patterns.md` by providing:
- More detailed compatibility assessment guidelines
- Hybrid workload examples combining free-threading with I/O operations
- Specific strategies for handling incompatibility scenarios
- Decision-making frameworks for choosing the appropriate execution model

Both documents should be consulted together for a complete understanding of concurrency options in Python 3.14+ within this codebase.
