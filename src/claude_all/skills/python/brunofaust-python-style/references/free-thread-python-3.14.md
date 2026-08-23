# Free-thread Python 3.14 — Reference Guide

## Overview

Python 3.14 introduces a new free-threaded implementation that allows for better parallelism and performance improvements in certain workloads. This reference guide covers when to use it, its pros and cons, implementation approaches, and compatibility considerations.

## When to Use

- **CPU-bound workloads** that can benefit from true parallelism
- **Applications with multiple event loops** that need to share threads
- **Projects requiring high concurrency** with minimal GIL contention

**Do not use**:
- For primarily I/O-bound workloads (use standard async patterns)
- With libraries that are not thread-safe
- When strict GIL behavior is required for compatibility

## Pros & Cons

### Pros
- **True parallelism**: Can utilize multiple CPU cores simultaneously
- **Improved performance**: For CPU-bound tasks and concurrent operations
- **Flexible event loop management**: Supports running multiple event loops in parallel

### Cons
- **GIL still present**: The GIL is still used for CPython compatibility, but free-thread allows bypassing in certain cases
- **Compatibility issues**: Some libraries may not work correctly with free-thread
- **Increased complexity**: Managing thread safety becomes the developer's responsibility

## Implementation

### Enabling Free-thread

To use the free-thread implementation, set the `PYTHONPIDs` environment variable to allow parallel execution:

```bash
export PYTHONPIDs=1
```

Alternatively, use the `InterpreterPoolExecutor` directly in your code:

```python
from concurrent.futures import InterpreterPoolExecutor

with InterpreterPoolExecutor() as executor:
    result = list(executor.map(your_function, your_data))
```

### Integration with Async Code

When combining free-thread with async code:

1. Use `run_in_thread` for blocking operations
2. Ensure all shared data structures are thread-safe
3. Use `asyncio.TaskGroup` for structured concurrency

Example hybrid approach:

```python
import asyncio
from concurrent.futures import InterpreterPoolExecutor

async def hybrid_compute(data: list[int]) -> list[int]:
    # CPU-bound parallel processing with free-thread
    with InterpreterPoolExecutor() as executor:
        parallel_results = list(executor.map(calculate, data))

    # Async I/O processing
    async def process_result(value: int) -> int:
        await async_io_operation(value)
        return value + 1

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(process_result(r)) for r in parallel_results]
        return [await task for task in tasks]
```

## Compatibility Checks

### Step 1: Dependency Audit

Ensure all dependencies are compatible with free-thread execution. Common issues:
- C extensions that assume single-threaded access
- Libraries that rely on GIL for thread safety

### Step 2: Test Suite

Add specific tests to verify free-thread compatibility:

```python
import pytest
from your_module import your_function

@pytest.mark.free_thread
def test_free_thread_compatibilty():
    with InterpreterPoolExecutor() as executor:
        result = executor.submit(your_function)
        assert result == expected
```

### Step 3: Monitoring

Implement runtime checks for free-thread compatibility:

```python
import sys

if sys.version_info >= (3, 14) and os.getenv('PYTHONPids') == '1':
    # Free-thread is active - ensure thread safety
    if not is_thread_safe(some_resource):
        raise RuntimeError('Thread-unsafe resource used in free-thread environment')

## Conclusion

The free-thread implementation in Python 3.14 provides powerful capabilities for parallelism but requires careful consideration of compatibility and thread safety. Use this guide to implement and verify free-thread usage in your application.
