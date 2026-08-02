# Free-threading in Python 3.14

Python 3.14 introduces significant improvements in handling concurrent execution, particularly with the adoption of **free-threading** via PEP 734 (InterpreterPoolExecutor). This feature allows true parallelism by leveraging multiple subinterpreters, each with its own GIL, enabling CPU-bound tasks to run concurrently without the limitations of a single GIL.

## When to Use Free-threading
Free-threading is ideal for CPU-bound tasks such as:
- Data processing (e.g., Polars operations)
- Machine learning inference
- Image/video processing
- Complex mathematical computations

Avoid using free-threading for I/O-bound operations, as these are better handled by asynchronous programming with `asyncio` and `uvloop`.

## Pros and Cons
### Pros
- **True Parallelism**: Utilizes multiple CPU cores effectively.
- **Simplified Concurrency**: High-level API with `InterpreterPoolExecutor`.
- **Compatibility**: Works with existing threading code where possible.

### Cons
- **Complexity**: Managing multiple interpreters adds overhead.
- **GIL Limitations**: Still subject to GIL for Python-specific operations.
- **Dependency Compatibility**: Requires dependencies to be thread-safe.

## Implementation
Use `concurrent.futures.InterpreterPoolExecutor` for CPU-bound tasks:

```python
from concurrent.futures import InterpreterPoolExecutor

with InterpreterPoolExecutor() as executor:
    results = list(executor.map(compute_square, range(100)))

# For Python-specific operations within threads, use run_in_thread:
import uvloop

def blocking_cpu_task(data):
    # CPU-bound task
    ...

async def process_data():
    result = await run_in_thread(blocking_cpu_task, data)
    ...
```

## Checking Dependency Compatibility
1. **Thread Safety**: Ensure libraries used are thread-safe or use thread-local storage.
2. **PEP 695 Generics**: Verify dependencies support Python 3.14 type annotations.
3. **PEP 758 Syntax**: Check for compatibility with paren-less `except` clauses.

To check:
- Review dependency documentation for thread safety.
- Test with `python -m pip check` for compatibility.
- Use `run_in_thread` for blocking operations within async code.

## References
- [`async-patterns.md`](async-patterns.md) for concurrency best practices
- [`threading-patterns.md`](threading-patterns.md) for advanced thread management
