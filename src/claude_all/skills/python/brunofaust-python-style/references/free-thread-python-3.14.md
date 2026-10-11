# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces **free-threading** capabilities through PEP 684 (Per-Interpreter GIL) and PEP 734 (InterpreterPoolExecutor). This allows multiple Python interpreters to run in parallel, each with its own Global Interpreter Lock (GIL), enabling true parallelism for Python code without the overhead of multiple processes.

Key aspects:
- **Subinterpreters**: Each interpreter has its own GIL, allowing concurrent execution of Python bytecode.
- **InterpreterPoolExecutor**: A `concurrent.futures` executor that runs tasks in separate subinterpreters.
- **Shareable data**: Only specific types can be shared between interpreters without pickling (`str`, `bytes`, `int`, `float`, `bool`, `None`, `tuple`, `memoryview`).
- **Relation to existing patterns**: Complements `run_in_thread()` for I/O-bound and C-extension work.

## Use Cases

### When to Use Free-Threading
- **CPU-bound pure Python work**: Parsing, mathematical computations, data transformation in pure Python.
- **Embarrassingly parallel tasks**: Work that can be split into independent chunks with minimal shared state.
- **Library-level parallelism**: When building libraries that need to utilize multiple cores for Python-level computations.

### When NOT to Use
- **I/O-bound work**: Use `async/await` + `run_in_thread()` instead (see `async-patterns.md`).
- **CPU-bound C extensions**: Many already release the GIL; use `run_in_thread()` for blocking calls.
- **Shared mutable state**: Complex to synchronize across interpreters; consider processes or threads with locks.

## Pros and Cons

### Pros
- **True parallelism**: Multiple CPU cores utilized for Python code (unlike threading constrained by GIL).
- **Lower overhead**: Subinterpreters share memory for read-only data and some objects, unlike processes.
- **Structured concurrency**: Works with `InterpreterPoolExecutor` similar to `ThreadPoolExecutor`.
- **Gradual adoption**: Can coexist with existing async and threading patterns.

### Cons
- **Data sharing restrictions**: Only picklable or shareable types can be passed between interpreters.
- **C extension compatibility**: Some extensions may not work correctly across subinterpreters (global state issues).
- **Limited mutable state sharing**: No efficient way to share mutable Python objects between interpreters.
- **Debugging complexity**: Issues may only manifest in multi-interpreter contexts.

## Implementation

### Basic Usage with InterpreterPoolExecutor

```python
from concurrent.futures import InterpreterPoolExecutor

def cpu_bound_task(n: int) -> int:
    """CPU-bound pure Python computation."""
    total = 0
    for i in range(n):
        total += i * i
    return total

# Using InterpreterPoolExecutor for parallel execution
with InterpreterPoolExecutor() as executor:
    futures = [executor.submit(cpu_bound_task, 1000000) for _ in range(4)]
    results = [f.result() for f in futures]
```

### Hybrid Approach (CPU + I/O)

For workloads combining CPU-bound pure Python and blocking I/O/C-extensions:

```python
import asyncio
from concurrent.futures import InterpreterPoolExecutor
from myproject.utils import run_in_thread  # Project's thread offloader

async def process_data(items):
    """Process items with hybrid CPU/I/O workload."""
    # CPU-bound pure Python: use InterpreterPoolExecutor
    with InterpreterPoolExecutor() as cpu_executor:
        cpu_futures = [
            cpu_executor.submit(heavy_computation, item)
            for item in items
        ]
        cpu_results = [f.result() for f in cpu_futures]
    
    # I/O-bound or C-extension work: use run_in_thread
    io_tasks = [
        run_in_thread(blocking_io_operation, result)
        for result in cpu_results
    ]
    return await asyncio.gather(*io_tasks)

def heavy_computation(data):
    """CPU-bound pure Python function."""
    # ... intensive computation ...
    return processed_data

def blocking_io_operation(data):
    """Blocking I/O or C-extension operation."""
    # ... file I/O, Polars, DeltaTable, etc. ...
    return result
```

### Checking Free-Threading Availability

```python
import sys
import _thread

def is_free_threadingSupported():
    """Check if free-threading (per-interpreter GIL) is available."""
    # Check if subinterpreters support is available (Python 3.12+)
    if hasattr(sys, "interpreters"):
        return True
    # Check if built with free-threading mode (GIL disabled)
    return getattr(_thread, "get", None) is not None  # Simplified check

# Note: Project baseline is Python 3.14+, so InterpreterPoolExecutor is available.
```

## Compatibility

### Checking Dependency Compatibility

#### For Subinterpreters (InterpreterPoolExecutor)
1. **Data types**: Ensure all arguments and return values are picklable or shareable types.
   - Shareable: `str`, `bytes`, `int`, `float`, `bool`, `None`, `tuple`, `memoryview`
   - Everything else must be picklable (passes `pickle.dumps()` / `pickle.loads()`).
2. **C extensions**: 
   - Must release the GIL during blocking operations (many already do).
   - Should not rely on process-global state that isn't shared across interpreters.
   - Test by running the extension in a subinterpreter context.

#### For Free-Threading Mode (Python built without GIL)
- **Extension modules**: Must be compatible with concurrent execution (no reliance on GIL for internal locks).
- **Pure Python**: Generally safe, but watch for implicit sharing via globals or classes.
- **Check**: Look for `_Py_GIL_DISABLED` or `Py_Gil_DISABLED` in build flags, or test with `sys._is_gil_enabled()` (if available).

### Project-Specific Guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms.
- Use `run_in_thread()` for:
  - Blocking I/O (file, network)
  - C extensions that don't release the GIL appropriately
  - Work requiring shared mutable state
- Use `InterpreterPoolExecutor` for:
  - CPU-bound pure Python
  - Tasks with minimal data sharing (only shareable/picklable types)

## Related Documentation
- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines.
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms.
- Consult `SKILL.md` for high-level skill conventions and recommendations.