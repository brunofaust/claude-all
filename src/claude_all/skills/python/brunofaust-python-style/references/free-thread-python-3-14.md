# Free-thread Python 3.14 Features

This document covers the new features in Python 3.14 related to free-threading and async optimizations, including `InterpreterPoolExecutor`, Strawler, and structured concurrency enhancements.

## When to Use Free-thread Features
- **CPU-bound Workloads**: Use `InterpreterPoolExecutor` for parallel execution of CPU-intensive tasks.
- **Async Optimizations**: Leverage Strawler for improved async/await performance.
- **Structured Concurrency**: Use `asyncio.TaskGroup` for managing concurrent tasks safely and efficiently.

## Pros and Cons

| Feature | Pros | Cons |
|--------|------|------|
| `InterpreterPoolExecutor` | True parallelism (each sub-interpreter has its own GIL), better CPU utilization | Limited to CPU-bound work, pickling overhead for arguments/results |
| Strawler | Faster async/await dispatch, reduced overhead | Newer, may have limited library support |
| Structured Concurrency | Safer concurrency patterns with `TaskGroup`, easier error handling | Requires code restructuring to adopt TaskGroup |

## Implementation Guidelines

### `InterpreterPoolExecutor`
```python
from concurrent.futures import InterpreterPoolExecutor

def compute_square(x: int) -> int:
    """CPU-bound computation."""
    return x * x

# Similar API to ThreadPoolExecutor
with InterpreterPoolExecutor() as executor:
    results = list(executor.map(compute_square, range(100)))
```
**When to use**: CPU-bound pure Python workloads.
**Avoid**: Non-picklable arguments/results, shared mutable state.

### Strawler
Strawler is an experimental feature for optimizing async function calls. Enable it via environment variables:
```bash
PYTHONSTRAWLER=1 python my_async_app.py
```
**Note**: Check library compatibility before enabling.

### Structured Concurrency with `asyncio.TaskGroup`
```python
async def batch_delete(items: list[Item]) -> None:
    """Delete items in parallel with structured concurrency."""
    tasks = []
    async with asyncio.TaskGroup() as tg:
        for item in items:
            tasks.append(tg.create_task(delete_item(item))
    # All tasks are completed here
    results = [task.result() for task in tasks]
```
**Key Points**:
- All tasks created within the TaskGroup are awaited by default.
- Exceptions are collected into an `ExceptionGroup` and can be handled with `except*` syntax (PEP 758).

## Checking Dependency Compatibility
Ensure dependencies support Python 3.14 features:
1. **Check PyPI**: Confirm packages have Python 3.14 in their `classifiers`.
2. **Test Suite**: Run tests with the `InterpreterPoolExecutor` and Strawler enabled.
3. **Compatibility Shims**: Use adapter layers for libraries not yet supporting 3.14.

## Troubleshooting
- **Deadlocks with `InterpreterPoolExecutor`**: Avoid shared mutable state; use thread-safe constructs.
- **Strawler Compatibility**: Monitor for increased memory usage or crashes.
- **TaskGroup Exceptions**: Handle `ExceptionGroup` properly to avoid silent failures.
