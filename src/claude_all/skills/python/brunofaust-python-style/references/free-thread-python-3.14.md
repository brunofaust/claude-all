# Python 3.14 Free-Threading Guide

> Reference page for the `brunofaust-python-style` skill. This file covers Python 3.14's free-threading feature (PEP 734) and how to use it effectively within the project's async-first conventions.

## Overview

Python 3.14 introduces free-threading via PEP 734, which provides the `InterpreterPoolExecutor` for true parallelism without the Global Interpreter Lock (GIL) constraints. Unlike traditional threading where only one thread can execute Python bytecode at a time due to the GIL, free-threading uses subinterpreters that each have their own GIL, enabling genuine parallel execution of Python code.

This feature complements the project's existing concurrency patterns:
- **`InterpreterPoolExecutor`**: For CPU-bound pure Python work requiring true parallelism
- **`run_in_thread()`**: For blocking code (C extensions, file I/O) where the GIL is already released
- **Async/await**: For I/O-bound work that doesn't block the event loop

The key insight is that free-threading is not a replacement for asyncio but another tool in the concurrency toolbox, best suited for specific CPU-bound scenarios.

## Use Cases

Free-threading with `InterpreterPoolExecutor` is most beneficial for:

| Scenario | Description | Example |
|----------|-------------|---------|
| **CPU-bound pure Python** | Mathematical computations, data parsing, algorithms | Image processing, statistical analysis, algorithmic trading |
| **Embarrassingly parallel** | Independent computations that don't share state | Monte Carlo simulations, parameter sweeps, batch processing |
| **Data transformation** | Pure functions applied to large datasets | ETL pipelines, data cleaning, feature extraction |

**When NOT to use free-threading:**
- Work requiring shared mutable state between workers
- Tasks heavily dependent on C extensions that don't release the GIL
- I/O-bound operations (use async/await or `run_in_thread()` instead)
- Very short-lived tasks where overhead outweighs benefits

## Pros and Cons

### Advantages
- **True parallelism**: Multiple CPU cores utilized simultaneously for Python code
- **Lower overhead**: Compared to `ProcessPoolExecutor` (no process serialization)
- **Same API**: Familiar `concurrent.futures` interface as `ThreadPoolExecutor`
- **Isolation**: Each subinterpreter has separate state, reducing interference risks
- **Performance**: Better scaling for CPU-bound pure Python workloads

### Limitations
- **Data sharing constraints**: Only picklable objects or limited shareable types can be passed between interpreters
- **C extension compatibility**: Extensions must be updated to work with multiple interpreters
- **Shared state issues**: Global variables, singletons, and module-level state are isolated per interpreter
- **Debugging complexity**: More complex error tracing across interpreter boundaries
- **Memory overhead**: Each interpreter maintains its own memory space

### Shareable Types (PEP 734)
Only these types can be shared between interpreters without pickling:
- `str | bytes | int | float | bool | None`
- `tuple` (containing only shareable types)
- `memoryview`

All other objects must be picklable to be passed between interpreters.

## Implementation

### Basic Usage

```python
from concurrent.futures import InterpreterPoolExecutor
from typing import List


def cpu_bound_computation(data: List[float]) -> float:
    """Example CPU-bound pure Python function."""
    # Simulate intensive computation (e.g., statistical processing)
    result = 0.0
    for x in data:
        result += x * x * 3.14159  # Some computation
    return result


def process_data_parallel(data_chunks: List[List[float]]) -> List[float]:
    """Process multiple data chunks in parallel using InterpreterPoolExecutor."""
    with InterpreterPoolExecutor(max_workers=4) as executor:
        # Map function to data chunks - each chunk processed in parallel
        results = list(executor.map(cpu_bound_computation, data_chunks))
    return results


# Alternative: Submit individual tasks
def process_with_submit(data_chunks: List[List[float]]) -> List[float]:
    with InterpreterPoolExecutor() as executor:
        futures = [executor.submit(cpu_bound_computation, chunk) for chunk in data_chunks]
        return [future.result() for future in futures]
```

### Hybrid CPU + I/O Workloads

For workloads that combine CPU-intensive processing with I/O operations, combine `InterpreterPoolExecutor` with async patterns:

```python
import asyncio
from concurrent.futures import InterpreterPoolExecutor
from typing import List


async def hybrid_processor(data_items: List[bytes]) -> List[dict]:
    """
    Process data with CPU-intensive parsing followed by async I/O.
    
    1. Use InterpreterPoolExecutor for CPU-bound parsing
    2. Use async/await for I/O operations (network, database)
    """
    # Step 1: CPU-bound parsing in parallel
    def parse_item(data: bytes) -> dict:
        # Simulate CPU-intensive parsing (pure Python)
        parsed = {
            "id": hash(data) & 0xFFFFFFFF,
            "length": len(data),
            "checksum": sum(data) % 256,
            # ... more complex parsing logic
        }
        # Additional CPU-intensive processing
        for i in range(1000):
            parsed["id"] = (parsed["id"] * 17 + 23) & 0xFFFFFFFF
        return parsed

    # Process parsing in parallel using interpreters
    with InterpreterPoolExecutor(max_workers=3) as executor:
        parsed_futures = [
            asyncio.get_event_loop().run_in_executor(executor, parse_item, item)
            for item in data_items
        ]
        parsed_results = await asyncio.gather(*parsed_futures)

    # Step 2: Async I/O operations (e.g., saving to database)
    async def save_result(result: dict) -> bool:
        # Simulate async database operation
        await asyncio.sleep(0.01)  # Replace with actual async DB call
        return True

    # Save all results concurrently using asyncio
    save_tasks = [save_result(result) for result in parsed_results]
    save_results = await asyncio.gather(*save_tasks)
    
    return [parsed_results[i] for i, saved in enumerate(save_results) if saved]


# Usage example
async def main():
    data_items = [b"sample data " + str(i).encode() for i in range(100)]
    results = await hybrid_processor(data_items)
    print(f"Processed {len(results)} items")


if __name__ == "__main__":
    asyncio.run(main())
```

### Integration with Project Patterns

Following the project's conventions from `async-patterns.md`, free-threading should be used selectively based on workload characteristics:

```python
from concurrent.futures import InterpreterPoolExecutor
from src.claude_all.hooks.python-thread-subprocess-guard import run_in_thread
import asyncio


def should_use_freethreading(workload_type: str) -> bool:
    """Determine if InterpreterPoolExecutor is appropriate based on workload."""
    cpu_bound_workloads = {
        "pure_python_computation",
        "data_parsing",
        "mathematical_processing",
        "statistical_analysis"
    }
    return workload_type in cpu_bound_workloads


async def process_workload(items: list, workload_type: str) -> list:
    """
    Process workload using the appropriate execution model.
    
    Follows project patterns:
    - InterpreterPoolExecutor for CPU-bound pure Python
    - run_in_thread() for blocking/C-extension work
    - Async/await for I/O-bound operations
    """
    if should_use_freethreading(workload_type):
        # CPU-bound pure Python -> InterpreterPoolExecutor
        def process_item(item):
            # Pure Python computation here
            return compute_intensive_task(item)
        
        with InterpreterPoolExecutor() as executor:
            loop = asyncio.get_event_loop()
            tasks = [
                loop.run_in_executor(executor, process_item, item)
                for item in items
            ]
            return await asyncio.gather(*tasks)
    
    elif workload_type in {"blocking_io", "c_extension"}:
        # Blocking work -> run_in_thread (project standard)
        return await asyncio.gather(
            *[run_in_thread(process_blocking_item, item) for item in items]
        )
    
    else:
        # I/O-bound or async-native -> direct async
        return await asyncio.gather(
            *[process_async_item(item) for item in items]
        )
```

## Compatibility

### Dependency Compatibility Checklist

Before using `InterpreterPoolExecutor` with a dependency, verify:

| Check | How to Verify | Action if Failed |
|-------|---------------|------------------|
| **C Extension GIL Release** | Does the extension release GIL during blocking calls? | Use `run_in_thread()` instead |
| **Picklability** | Are inputs/outputs picklable? | Convert to shareable types or use `run_in_thread()` |
| **Shared State** | Does dependency rely on global/module state? | Isolate usage or use `run_in_thread()` |
| **Subinterpreter Support** | Is extension compatible with multiple interpreters? | Check documentation or test; use `run_in_thread()` if incompatible |
| **Memory Management** | Does extension allocate memory safely across interpreters? | Test thoroughly; prefer `run_in_thread()` if unsure |

### Project-Specific Guidelines

Following the patterns established in the codebase:

1. **Check `async-patterns.md` first**: The file already provides guidance on when to use `InterpreterPoolExecutor` vs `run_in_thread()`

2. **Follow the banned-api rules**: The project prohibits direct use of `asyncio.to_thread` and `ThreadPoolExecutor` in favor of the centralized `run_in_thread()` function

3. **Use the thread pool owner**: All blocking work should go through `run_in_thread()` which manages the global `BLOCKING_THREADPOOL`

4. **Apply the same decision matrix**: 
   - **CPU-bound pure Python** → `InterpreterPoolExecutor`
   - **Blocking I/O or C extensions** → `run_in_thread()`
   - **I/O-bound async** → Direct await

### Testing Compatibility

To test if a dependency works with free-threading:

```python
def test_dependency_compatibility():
    """Test if a dependency works with InterpreterPoolExecutor."""
    from concurrent.futures import InterpreterPoolExecutor
    
    # Test 1: Basic functionality
    def uses_dependency(x):
        # Call the dependency here
        result = some_dependency_function(x)
        return result
    
    # Test 2: Data passing (picklability check)
    try:
        with InterpreterPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(uses_dependency, i)
                for i in range(10)
            ]
            results = [f.result() for f in futures]
        return True, "Dependency compatible"
    except Exception as e:
        return False, f"Dependency incompatible: {e}"

# Usage
compatible, message = test_dependency_compatibility()
if not compatible:
    logger.warning(f"Skipping free-threading for dependency: {message}")
    # Fall back to run_in_thread()
```

### Handling Incompatibilities

When dependencies are incompatible with free-threading:

1. **Isolate usage**: Run incompatible dependencies in dedicated threads via `run_in_thread()`
2. **Version pinning**: Use compatible versions that support subinterpreters
3. **Wrapper functions**: Create thin wrappers that handle data conversion
4. **Fallback strategy**: Implement graceful degradation to thread-based execution

Example fallback pattern:
```python
def safe_process_with_fallback(data):
    """Try free-threading, fall back to thread pool if incompatible."""
    try:
        # Attempt free-threading approach
        with InterpreterPoolExecutor() as executor:
            return list(executor.map(process_item, data))
    except (TypeError, AttributeError) as e:
        # Fallback to run_in_thread for incompatible dependencies
        logger.warning(f"Free-threading failed ({e}), falling back to run_in_thread")
        return asyncio.gather(*[run_in_thread(process_item, item) for item in data])
```

## Best Practices

### Do
- Profile your workload to confirm it's CPU-bound before using free-threading
- Test dependencies thoroughly for subinterpreter compatibility
- Use shareable types (`str`, `int`, `tuple` of primitives) when possible
- Keep interpreter workloads focused on pure Python computation
- Follow the project's existing patterns for mixing execution models
- Monitor memory usage as each interpreter has separate memory space

### Don't
- Assume all CPU-bound work benefits equally (measure first)
- Pass complex objects between interpreters without verifying picklability
- Rely on shared global state between interpreter workers
- Use free-threading for I/O-bound work (use async/await instead)
- Forget to handle exceptions properly across interpreter boundaries
- Overlook the overhead for very small tasks

## When to Reach For This

Use free-threading (`InterpreterPoolExecutor`) when:
- You have **CPU-bound pure Python** work that can be parallelized
- The work involves **independent computations** (embarrassingly parallel)
- You need **true parallelism** beyond what asyncio can provide
- Dependencies are **verified compatible** with subinterpreters
- You've **profiled** and confirmed performance benefits

Reach for `run_in_thread()` when:
- Work involves **blocking I/O** (file, network, database)
- Dependencies are **C extensions** that release the GIL
- You need **shared state** between workers
- Dependencies are **incompatible** with subinterpreters
- Work involves **brief blocking calls** where thread overhead is acceptable

## Related References

- [`async-patterns.md`](#): Detailed comparison of `InterpreterPoolExecutor` vs `run_in_thread()`
- [`execution-models.md`](#): Guidance on choosing between async, threading, and multiprocessing
- [`thread-pool.py`](#): Implementation of `run_in_thread()` as the single owner of thread-offload
- [`SKILL.md`](#): Skill-level summary of concurrency patterns

## Further Reading

- [PEP 734 – Allowing Extension Modules to Initialize Multiple Interpreter States](https://peps.python.org/pep-0734/)
- [Python 3.14 What's New](https://docs.python.org/3.14/whatsnew/3.14.html)
- [Subinterpreter Documentation](https://docs.python.org/3.14/library/interpreters.html)