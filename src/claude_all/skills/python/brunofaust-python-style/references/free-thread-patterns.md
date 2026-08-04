# Python 3.14 Free-Threading
## `InterpreterPoolExecutor` Guide

### What is Free-Threading?
**Free-threading** in Python 3.14, via `concurrent.futures.InterpreterPoolExecutor`, enables true parallelism by leveraging multiple sub-interpreters, each with its own GIL. This is particularly useful for CPU-bound tasks.

### When to Use
- **CPU-bound**:Optimal for intensive computations (e.g., data processing, ML inference).
- **Avoid for I/O-bound**: Use `run_in_thread()` instead.

### Implementation Example
```python
from concurrent.futures import InterpreterPoolExecutor

def cpu_bound_task(n: int) -> int:
    """Example CPU-bound task."""
    return sum(i * i for i in range(n))

def main():
    with InterpreterPoolExecutor() as executor:
        results = list(executor.map(cpu_bound_task, range(100)))
    print(results)
    uvloop.run(main)
```

### Pros and Cons
| **Pros** | **Cons** |
|----------|----------|
| True parallelism | No shared mutable state |
| Lower overhead | Limited to CPU-bound |
| Simple API | Requires Python 3.14+ |

### Checking Dependency Compatibility
- Verify Python version: `python --version`
- Check dependency support in `pyproject.toml` or `setup.py`.

### Security and Performance
- **Thread Safety**: Avoid shared mutable state; use thread-safe structures if necessary.
- **Resource Limits**: Monitor and limit concurrency to avoid exhaustion.

### See Also
- `async-patterns.md` for I/O-bound concurrency.
- `caching.md` for performance optimizations.
