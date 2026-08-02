## Python 3.14 Free-Threading Guide

### Overview
Python 3.14 introduces **free-threading** via `concurrent.futures.InterpreterPoolExecutor` (PEP 734), enabling true parallelism for CPU-bound pure Python code by bypassing the Global Interpreter Lock (GIL) across subinterpreters.

### When to Use
Use `InterpreterPoolExecutor` for:
- **CPU-bound pure Python work** (e.g., data transforms, mathematical computations)
- **Parallelizing picklable tasks** (arguments/results must be picklable)

Avoid for:
- Blocking I/O or C extensions (use `run_in_thread`)
- Shared mutable state (subinterpreters isolate state)
- Non-picklable data exchange

### Pros and Cons
| **Pros** | **Cons** |
|----------|-----------|
| True parallelism (bypasses GIL) | Pickling constraints (only `str`, `int`, `tuple`, etc.) |
| Lower overhead than `ProcessPoolExecutor` | C extensions may not work across interpreters |
| Familiar `Executor` API | Risk of data races with shared state |

### Implementation
```python
from concurrent.futures import InterpreterPoolExecutor

def compute_square(x: int) -> int:
    """CPU-bound computation."""
    return x * x

# Usage
with InterpreterPoolExecutor() as executor:
    results = list(executor.map(compute_square, range(100)))
```

**Key Practices:**
- Avoid shared mutable objects (lists, dicts) across interpreters
- Use thread-safe structures or queues for cross-interpreter communication
- Prefer picklable types for task inputs/outputs

### Dependency Compatibility Checks
1. **Audit Libraries:** Ensure third-party libraries are subinterpreter-safe (no shared global state)
2. **Test Picklability:**
   ```python
   import pickle
   try:
       pickle.dumps(custom_object)
   except pickle.PicklingError as e:
       # Handle non-picklable types
   ```
3. **Monitor Data Races:** Use logging/debugging tools to detect unexpected state changes in shared resources
