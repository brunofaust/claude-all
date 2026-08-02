# Python 3.14 Free-thread Feature (Subinterpreters / PEP 703)

## Overview
Python 3.14 introduces the ability to run multiple subinterpreters concurrently (via **PEP 703**), enabling true parallel execution without the Global Interpreter Lock (GIL). This is a significant shift from Python’s traditional single-interpreter model, allowing CPU-bound tasks to leverage multiple cores effectively.

## When to Use
### Ideal Use Cases
1. **CPU-bound tasks:** Heavy computations like data transformation, image processing, or machine learning.
2. **Standalone parallel tasks:** Independent operations where results don’t interleave (e.g., batch processing).
3. **Complementary to async:** Use free-threading for CPU work; combine with `asyncio` for I/O-bound tasks.

### Avoid When
- **I/O-bound workloads:** Use `asyncio` and `await` instead.
- **Shared-state operations:** Race conditions are harder to manage across interpreters.
- **Libraries not thread-safe:** If dependencies assume a single GIL.

## Pros and Cons
### Pros
- **True parallelism:** Utilizes all available CPU cores.
- **Scalability:** Linear speedup for embarrassingly parallel workloads.
- **Compatibility:** Backward-compatible with most thread-safe libraries.

### Cons
- **Memory overhead:** Each subinterpreter has its own memory space.
- **Complexity:** Requires careful resource management (e.g., shared state).
- **Library limitations:** Many existing packages assume a single interpreter.

## Implementation
### 1. Using `InterpreterPoolExecutor` (Recommended)
```python
from concurrent.futures import InterpreterPoolExecutor

def compute_square(x):
    """CPU-bound task."""
    return x * x

# Execute in parallel across subinterpreters
with InterpreterPoolExecutor() as executor:
    results = list(executor.map(compute_square, range(100)))
"""
# Note: This example assumes a CPU-bound task that can be parallelized
# without shared state. Adjust based on your actual workload.
"""

### 2. Manual Subinterpreter Management (Advanced)
Use `sys.setswitchinterval()` and `sys.settracemask()` for fine-grained control (requires deep understanding of Python internals).

## Checking Dependency Compatibility
### 1. Thread-safety
- Ensure dependencies are designed for concurrent access (e.g., use thread-safe data structures).
- Avoid libraries that assume a single GIL.

### 2. C Extensions
- Libraries like **NumPy** or **Pandas** often release the GIL during operations and are compatible.
- Test with `import numpy; numpy.show_config()` to verify C-based optimizations.

### 3. Version-Specific Tests
```python
import os
import traceback

def test_thread_safe():
    try:
        # Example: Stress-test a dependency
        from my_dependency import heavy_operation
        with InterpreterPoolExecutor() as executor:
            list(executor.map(heavy_operation, range(1000)))
    except Exception as e:
        print(f"Thread safety test failed: {traceback.format_exc()}")
        raise
```

## Best Practices
1. **Prefer `InterpreterPoolExecutor`** over manual thread management.
2. **Use `run_in_thread()` for blocking CPython calls** (if library can’t release GIL).
3. **Isolate state:** Avoid sharing mutable objects across interpreters.
4. **Monitor memory usage:** Each subinterpreter has its own memory space.

## References
- [PEP 703 – Subinterpreters](https://peps.python.org/pep-0703/)
- [`async-patterns.md`](../async-patterns.md) for combining with async code
- [`test-safety.md`](../test-safety.md) for thread-safe testing
