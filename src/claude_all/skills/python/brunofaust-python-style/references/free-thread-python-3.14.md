# Free-threading in Python 3.14 — Reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces **free-threading** via PEP 734, which adds `InterpreterPoolExecutor` to the standard library. This feature provides true parallelism by utilizing subinterpreters, each with its own Global Interpreter Lock (GIL), allowing multiple CPU-bound threads to run in parallel without GIL contention.

### Relation to GIL and InterpreterPoolExecutor

- **Traditional GIL limitation**: In Python < 3.14, the GIL prevents true parallelism of CPU-bound threads, limiting performance on multi-core systems.
- **Subinterpreters**: PEP 734 introduces subinterpreters, each with its own GIL, enabling true parallelism.
- **InterpreterPoolExecutor**: A `concurrent.futures.Executor` implementation that manages a pool of subinterpreters, providing an API similar to `ThreadPoolExecutor` and `ProcessPoolExecutor`.

Free-threading is **not** the same as removing the GIL entirely; rather, it provides isolated interpreters that can each acquire their own GIL, allowing parallel execution across interpreters.

## Use Cases

Free-threading via `InterpreterPoolExecutor` is beneficial for:

- **CPU-bound pure Python work**: Mathematical computations, data parsing, algorithms that don't rely on shared mutable state.
- **Workloads requiring true parallelism**: When you need to utilize multiple CPU cores effectively for pure Python tasks.
- **Lower-overhead parallelism**: Compared to `ProcessPoolExecutor`, subinterpreters have lower memory overhead and faster startup times.

**Do not use free-threading for**:
- Blocking I/O operations (file, network) — use `run_in_thread()` instead.
- CPU-bound work that relies on C extensions — C extensions may not release the GIL or may have global state issues across interpreters.
- Tasks requiring shared mutable state between workers — subinterpreters are isolated and do not share memory.

## Pros and Cons

### Advantages

| Benefit | Description |
|---------|-------------|
| **True parallelism** | Multiple CPU-bound threads run in parallel across subinterpreters, each with its own GIL. |
| **Lower overhead** | Subinterpreters have lower memory overhead and faster startup/teardown than processes. |
| **Similar API** | `InterpreterPoolExecutor` follows the `concurrent.futures.Executor` API, making it easy to adopt. |
| **No serialization for shareable types** | Certain immutable types (`str`, `bytes`, `int`, `float`, `bool`, `None`, `tuple`, `memoryview`) can be shared without pickling. |

### Limitations

| Limitation | Description |
|------------|-------------|
| **Isolated state** | Subinterpreters do not share memory; objects must be picklable to pass between them (except for shareable types). |
| **Pickling requirements** | Arguments and return values must be picklable unless they are shareable types. |
| **C extension compatibility** | C extensions that use global state or don't properly release the GIL may not work correctly. |
| **No shared mutable state** | Cannot share mutable objects directly between interpreters; must use message passing (pickling). |
| **Debugging complexity** | Issues may be harder to diagnose due to interpreter isolation. |

## Implementation

### Basic Usage

For CPU-bound pure Python tasks, use `InterpreterPoolExecutor` directly:

```python
from concurrent.futures import InterpreterPoolExecutor


def compute_factorial(n: int) -> int:
    """CPU-bound computation: calculate factorial."""
    if n < 0:
        raise ValueError("Factorial is not defined for negative numbers")
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result


def process_numbers(numbers: list[int]) -> list[int]:
    """Process a list of numbers in parallel using free-threading."""
    with InterpreterPoolExecutor() as executor:
        # Map the function to each number - arguments and results are pickled
        results = list(executor.map(compute_factorial, numbers))
    return results


# Example usage
if __name__ == "__main__":
    numbers = [5, 7, 10, 12, 15]
    factorials = process_numbers(numbers)
    print(factorials)  # [120, 5040, 3628800, 479001600, 1307674368000]
```

### Hybrid CPU + I/O Workloads

For workloads that combine CPU-bound pure Python work with I/O operations, use a hybrid approach:
- Use `InterpreterPoolExecutor` for the CPU-bound pure Python portions
- Use `run_in_thread()` for I/O operations or C extension work

```python
from concurrent.futures import InterpreterPoolExecutor
from pathlib import Path
import json

# Assuming run_in_thread is available from your thread utilities
# from thread import run_in_thread  # Import from your project's thread utilities


def parse_json_file(file_path: Path) -> dict:
    """CPU-bound task: parse JSON file contents (pure Python)."""
    # This is CPU-bound pure Python work suitable for InterpreterPoolExecutor
    return json.loads(file_path.read_text())


def save_json_file(data: dict, file_path: Path) -> None:
    """I/O task: write JSON data to file (blocking disk I/O)."""
    # This is blocking I/O - better suited for run_in_thread
    file_path.write_text(json.dumps(data, indent=2))


async def process_data_files(file_paths: list[Path]) -> list[dict]:
    """Process multiple JSON files with hybrid CPU/I/O workload."""
    # Step 1: Read and parse files in parallel (CPU-bound)
    with InterpreterPoolExecutor() as executor:
        parsed_data = list(executor.map(parse_json_file, file_paths))

    # Step 2: Process the parsed data (example: add metadata)
    processed_data = []
    for data in parsed_data:
        data["processed_at"] = "2026-09-04T00:00:00Z"  # Example metadata
        processed_data.append(data)

    # Step 3: Save results (I/O-bound - use run_in_thread)
    save_tasks = []
    for i, data in enumerate(processed_data):
        output_path = file_paths[i].with_suffix(".processed.json")
        # Offload the blocking I/O operation to a thread
        task = run_in_thread(save_json_file, data, output_path)
        save_tasks.append(task)

    # Wait for all save operations to complete
    await asyncio.gather(*save_tasks)

    return processed_data
```

### Important Implementation Notes

1. **Picklability**: Only picklable objects can be passed between interpreters (except shareable types). Ensure your function arguments and return values meet this requirement.
2. **Shareable types**: The following types can be shared without pickling: `str | bytes | int | float | bool | None | tuple | memoryview`.
3. **Error handling**: Exceptions raised in worker functions are propagated and can be caught in the main thread.
4. **Resource management**: Always use `InterpreterPoolExecutor` as a context manager (`with` statement) or call `shutdown()` explicitly.

## Compatibility

### Dependency Compatibility Checks

Before using `InterpreterPoolExecutor` with a dependency, verify the following:

| Check | How to Verify | Action if Failed |
|-------|---------------|------------------|
| **C extension GIL release** | Check if the extension releases the GIL during blocking operations (most do for I/O, but not for CPU work) | Use `run_in_thread()` instead for CPU-bound C extension work |
| **Picklable arguments/results** | Verify that all data passed to/from the function is picklable (or uses shareable types) | Refactor to use only picklable/shareable types, or use `run_in_thread()` |
| **No shared mutable state** | Ensure the function doesn't rely on mutable global state or shared objects | Refactor to avoid shared state, or use `run_in_thread()` |
| **Interpreter-safe C extensions** | Confirm C extensions don't use process-global state that would break across interpreters | Avoid using with `InterpreterPoolExecutor`; use `run_in_thread()` instead |

### Strategies for Handling Incompatibilities

1. **Selective offloading**: Use `InterpreterPoolExecutor` for pure Python CPU-bound components and `run_in_thread()` for incompatible components:
   ```python
   # Pure Python CPU-bound part -> InterpreterPoolExecutor
   pure_python_result = await run_in_interpreter(pure_python_func, data)

   # Incompatible C extension part -> run_in_thread
   final_result = await run_in_thread(c_extension_func, pure_python_result)
   ```

2. **Fallback pattern**: Attempt to use `InterpreterPoolExecutor` and fall back to `run_in_thread()` on compatibility errors:
   ```python
   async def safe_parallel_process(func, *args):
       try:
           with InterpreterPoolExecutor() as executor:
               return await loop.run_in_executor(executor, func, *args)
       except (TypeError, PicklingError) as e:
           # Fall back to thread pool for incompatible workloads
           return await run_in_thread(func, *args)
   ```

3. **Data boundary adaptation**: Convert data to compatible formats at interpreter boundaries:
   - Convert complex objects to picklable formats (e.g., dicts, tuples) before passing to interpreters
   - Reconstruct objects in the worker function if needed
   - Use shareable types where possible for high-performance data transfer

4. **Isolation boundaries**: Keep interpreter-incompatible work isolated in dedicated functions that are offloaded via `run_in_thread()`:
   ```python
   # Incompatible work isolated in this function
   def incompatible_work(data):
       # Uses C extensions with global state, mutable objects, etc.
       return c_extension_heavy_processing(data)

   # Compatible pure Python work
   def compatible_work(data):
       # Pure Python, picklable arguments/results
       return python_cpu_bound_processing(data)

   # Usage: compatible work in interpreters, incompatible in threads
   interpreter_results = []
   with InterpreterPoolExecutor() as executor:
       interpreter_results = list(executor.map(compatible_work, data_chunks))

   final_results = await asyncio.gather(
       *[run_in_thread(incompatible_work, result) for result in interpreter_results]
   )
   ```

### Project-Specific Guidelines

Following the patterns established in this skill:

- **Use `InterpreterPoolExecutor` for**: CPU-bound pure Python tasks that meet picklability requirements.
- **Use `run_in_thread()` for**:
  - Blocking I/O operations (file, network, etc.)
  - CPU-bound work relying on C extensions
  - Tasks requiring shared mutable state
  - Any workload that fails the compatibility checks above
- **Never use**: `asyncio.to_thread` or raw `ThreadPoolExecutor` — all thread offloading must go through the project's `run_in_thread()` wrapper (the single owner of the thread-offload seam).

The project maintains strict rules about when to use each executor, enforced via:
- `async-patterns.md` documentation
- Banned-api Prek hooks for `asyncio.to_thread` and raw `ThreadPoolExecutor`
- The `thread_pool.py` module providing `run_in_thread()` as the single owner
