# Subinterpreters — Python 3.14+

> Reference page for the `brunofaust-python-style` skill. This document covers Python 3.14's subinterpreter feature (PEP 734).

## Overview

Python 3.14 introduces **subinterpreters** (PEP 734), enabling parallel execution of Python code by providing isolated interpreters each with their own Global Interpreter Lock (GIL). This allows multiple threads to execute Python bytecode simultaneously without the overhead of processes.

This feature is accessed through `concurrent.futures.InterpreterPoolExecutor`, which provides a similar API to `ThreadPoolExecutor` and `ProcessPoolExecutor` but with true parallelism for Python code.

## When to Use Free-threading

### ✅ Use InterpreterPoolExecutor when:

- **CPU-bound pure Python work** (parsing, mathematical computations, data processing)
- **Work that doesn't require sharing mutable state** between threads
- **You need true parallelism** (multiple CPU cores utilized simultaneously)
- **Lower overhead than processes** is desired (faster startup, less memory)
- **Your project's minimum Python version is 3.14+**

### ❌ Avoid InterpreterPoolExecutor when:

- **Work requires sharing mutable state** (subinterpreters are isolated)
- **Using C extensions that rely on global state** (may not work correctly)
- **Need to share complex objects** between workers (limited to shareable types)
- **Working with already-GIL-releasing C extensions** (use `run_in_thread` instead)
- **Blocking I/O operations** (use `run_in_thread` — simpler and lower overhead)

## Pros and Cons

### Pros:

- **True parallelism**: Multiple CPU cores can execute Python bytecode simultaneously
- **Lower overhead**: Faster startup and lower memory usage vs `ProcessPoolExecutor`
- **Similar API**: Familiar `concurrent.futures` interface
- **Isolation**: Each subinterpreter has separate state, reducing side effects
- **No GIL contention**: Each interpreter has its own GIL

### Cons:

- **Isolation limitations**: No shared mutable state between interpreters
- **Data sharing restrictions**: Only specific shareable types can be passed without pickling
- **C extension compatibility**: Some C extensions may not work correctly across interpreters
- **Python 3.14+ only**: Not available on older Python versions
- **Pickling required**: Most complex objects must be pickled for transfer

## How to Implement

### Basic Usage

```python
from concurrent.futures import InterpreterPoolExecutor


def compute_square(x: int) -> int:
    """CPU-bound computation."""
    return x * x


# Similar API to ThreadPoolExecutor / ProcessPoolExecutor
with InterpreterPoolExecutor() as executor:
    results = list(executor.map(compute_square, range(100)))
```

### Submitting Individual Tasks

```python
from concurrent.futures import InterpreterPoolExecutor
import time


def cpu_bound_task(n: int) -> int:
    """Simulate CPU-intensive work."""
    total = 0
    for i in range(n):
        total += i * i
    return total


def main():
    with InterpreterPoolExecutor(max_workers=4) as executor:
        # Submit tasks
        futures = [
            executor.submit(cpu_bound_task, 1000000),
            executor.submit(cpu_bound_task, 2000000),
            executor.submit(cpu_bound_task, 1500000),
        ]

        # Collect results
        results = [f.result() for f in futures]
        print(f"Results: {results}")


if __name__ == "__main__":
    main()
```

### Sharing Data Limitations

Only these types can be shared between interpreters without pickling:
- `str | bytes | int | float | bool | None | tuple | memoryview`

For other types, automatic pickling occurs (similar to `ProcessPoolExecutor`):

```python
from concurrent.futures import InterpreterPoolExecutor


def process_data(data: dict) -> dict:
    """Process dictionary data (will be pickled)."""
    return {k: v * 2 for k, v in data.items()}


def main():
    data = {"a": 1, "b": 2, "c": 3}

    with InterpreterPoolExecutor() as executor:
        future = executor.submit(process_data, data)
        result = future.result()
        print(f"Processed: {result}")


if __name__ == "__main__":
    main()
```

## When to Use Free-threading vs Alternatives

| Situation                                  | Recommended Approach               |
| ------------------------------------------ | ---------------------------------- |
| CPU-bound pure Python (parsing, math)      | `InterpreterPoolExecutor`          |
| CPU-bound C extension (Polars, DeltaTable) | `run_in_thread`                    |
| Blocking I/O (file, network)               | `run_in_thread`                    |
| Needs shared mutable state                 | `run_in_thread` or threading.Lock  |
| Already async work                         | `await` directly                   |

## Checking Dependency Compatibility

### 1. **Check for Global State in C Extensions**

The primary compatibility concern is C extensions that use global state. To check:

```python
import sys
import ctypes


def check_extension_global_state(module_name: str) -> bool:
    """Heuristic check for potential global state issues."""
    try:
        module = __import__(module_name)
        # Check if module has module-level variables that might be problematic
        # This is a heuristic - actual testing is required
        return hasattr(module, '_global_state') or hasattr(module, 'static_data')
    except ImportError:
        return False
```

### 2. **Test with InterpreterPoolExecutor**

The most reliable method is actual testing:

```python
from concurrent.futures import InterpreterPoolExecutor
import your_dependency as dep


def test_dependency_in_subinterpreter():
    """Test if dependency works correctly in subinterpreter context."""
    try:
        # Run dependency operation in subinterpreter
        with InterpreterPoolExecutor(max_workers=2) as executor:
            future = executor.submit(dep.some_cpu_bound_function, test_data)
            result = future.result(timeout=30)
            # Validate result is correct
            return validate_result(result)
    except Exception as e:
        print(f"Dependency failed in subinterpreter: {e}")
        return False


# Run compatibility test
if test_dependency_in_subinterpreter():
    print("Dependency is compatible with free-threading")
else:
    print("Dependency may have issues with free-threading")
```

### 3. **Consult Documentation and Resources**

- **Python Documentation**: [PEP 734 – Subinterpreters for the standard library](https://peps.python.org/pep-0734/)
- **PyPI Package Checkers**: Look for packages that explicitly mention Python 3.14/subinterpreter support
- **Community Resources**: Check discussions in Python forums, GitHub issues for your dependencies
- **Testing in Isolation**: Create a minimal reproduction to test dependency behavior

### 4. **Using python -m perf for Validation**

Performance testing can reveal issues:

```bash
# Test performance scaling
python3.14 -m perf timeit -s "from concurrent.futures import InterpreterPoolExecutor; import math" \
    "list(InterpreterPoolExecutor().map(math.isqrt, range(10000)))"
```

### 5. **Check for Known Incompatible Patterns**

Dependencies may be incompatible if they:
- Use static/global variables in C extensions
- Rely on thread-local storage that doesn't translate to interpreter-local storage
- Use C APIs that assume single interpreter state
- Have interpreter-specific initialization that doesn't work when called multiple times

## Best Practices

### 1. **Version Gating**

Only use InterpreterPoolExecutor when running Python 3.14+:

```python
import sys
from concurrent.futures import InterpreterPoolExecutor, ProcessPoolExecutor


def get_executor():
    """Return appropriate executor based on Python version."""
    if sys.version_info >= (3, 14):
        return InterpreterPoolExecutor
    else:
        return ProcessPoolExecutor  # Fallback for older versions


# Usage
ExecutorClass = get_executor()
with ExecutorClass(max_workers=4) as executor:
    # ... submit tasks
```

### 2. **Graceful Degradation**

Handle cases where free-threading isn't available:

```python
def run_cpu_bound_work(tasks):
    """Run CPU-bound work with fallback."""
    try:
        from concurrent.futures import InterpreterPoolExecutor
        executor_type = InterpreterPoolExecutor
    except ImportError:
        # Python < 3.14
        from concurrent.futures import ProcessPoolExecutor
        executor_type = ProcessPoolExecutor

    with executor_type() as executor:
        return list(executor.map(process_task, tasks))
```

### 3. **Isolation Awareness**

Design tasks to work in isolation:
- Avoid sharing mutable state between tasks
- Pass all required data as function arguments
- Return results rather than modifying external state
- Use immutable data structures when possible

### 4. **Error Handling**

Handle interpreter-specific errors:

```python
from concurrent.futures import InterpreterPoolExecutor
import pickle


def safe_subinterpreter_task(func, *args):
    """Wrap task to handle pickling/interpreter issues."""
    try:
        return func(*args)
    except pickle.PicklingError as e:
        raise ValueError(f"Arguments not shareable/picklable: {e}") from e
    except RuntimeError as e:
        if "interpreter" in str(e).lower():
            raise RuntimeError(f"Subinterpreter compatibility issue: {e}") from e
        raise
```

## Migration Guide

### From ThreadPoolExecutor

```python
# Before (ThreadPoolExecutor - limited by GIL)
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor() as executor:
    results = list(executor.map(cpu_bound_task, work_items))

# After (InterpreterPoolExecutor - true parallelism)
from concurrent.futures import InterpreterPoolExecutor

with InterpreterPoolExecutor() as executor:
    results = list(executor.map(cpu_bound_task, work_items))
```

### From ProcessPoolExecutor

```python
# Before (ProcessPoolExecutor - higher overhead)
from concurrent.futures import ProcessPoolExecutor

with ProcessPoolExecutor() as executor:
    results = list(executor.map(cpu_bound_task, work_items))

# After (InterpreterPoolExecutor - lower overhead)
from concurrent.futures import InterpreterPoolExecutor

with InterpreterPoolExecutor() as executor:
    results = list(executor.map(cpu_bound_task, work_items))
```

## References

- [PEP 734 – Subinterpreters for the standard library](https://peps.python.org/pep-0734/)
- [Python 3.14 What's New](https://docs.python.org/3/whatsnew/3.14.html#subinterpreters)
- [concurrent.futures.InterpreterPoolExecutor documentation](https://docs.python.org/3/library/concurrent.futures.html#interpreterpoolexecutor)
- [Shareable types documentation](https://docs.python.org/3/library/interpreters.html#shareable-types)
