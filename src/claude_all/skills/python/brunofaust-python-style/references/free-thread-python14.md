## Free-thread Python 3.14

### Introduction
Python 3.14 introduces new features for parallelism and concurrency. This guide covers the `InterpreterPoolExecutor` and other threading models.

### Use Cases
- **CPU-bound tasks**: Utilize `InterpreterPoolExecutor` for true parallelism.
- **I/O-bound tasks**: Use `run_in_thread` for asynchronous operations.

### Pros and Cons
| Approach | Pros | Cons |
|---------|------|------|
| InterpreterPoolExecutor | True parallelism, efficient for CPU tasks | Not suitable for I/O, shared state issues |
| run_in_thread | Simple, works with async code | Overhead for creating threads |

### Implementation Examples
#### InterpreterPoolExecutor
```python
from concurrent.futures import InterpreterPoolExecutor

def compute_square(x: int) -> int:
    """CPU-bound computation."""
    return x * x

# Usage
with InterpreterPoolExecutor() as executor:
    results = list(executor.map(compute_square, range(100)))
```

#### run_in_thread
```python
import asyncio
from your_project.core.thread_pool import run_in_thread

async def fetch_data():
    """I/O-bound task."""
    await run_in_thread(blocking_io_operation)
```

### Dependency Compatibility
Ensure all dependencies support Python 3.14. Check for:
- Library compatibility (e.g., `asyncio`, `concurrent.futures`)
- No usage of deprecated features

### Troubleshooting
- **Performance Issues**: Monitor GIL contention for `InterpreterPoolExecutor`.
- **Deadlocks**: Avoid shared mutable state with `InterpreterPoolExecutor`.
