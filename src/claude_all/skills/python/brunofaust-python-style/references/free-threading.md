# Free-threading in Python 3.14

## Overview
Python 3.14 introduces **free-threading** capabilities via `InterpreterPoolExecutor` (PEP 734), enabling true parallelism using multiple sub-interpreters. This complements async I/O patterns, providing a way to run CPU-bound tasks in parallel without GIL restrictions.

## When to Use

### CPU-bound tasks
Use free-threading for:
- Heavy computations (e.g., data processing, ML inference)
- Parallelizing independent tasks (e.g., batch processing)
- Utilizing multiple CPU cores

### I/O-bound tasks
**Avoid** free-threading; use async patterns:
- Network requests (HTTP, DB)
- File I/O
- External service calls

## Pros and Cons

| Pros | Cons |
|------|------|
| ✅ True parallelism for CPU work | ⚠️ Risk of race conditions |
| ✅ Leverages multi-core CPUs | ⚠️ Increased complexity |
| ✅ Simplified parallel loops | ⚠️ Harder to debug |

## Implementation Patterns

### 1. InterpreterPoolExecutor (PEP 734)
```python
from concurrent.futures import InterpreterPoolExecutor

# Similar to ThreadPoolExecutor but uses sub-interpreters
with InterpreterPoolExecutor() as executor:
    results = list(executor.map(cpu_bound_task, inputs))
```

### 2. `asyncio.to_thread` for Blocking Code
```python
async def handle_request():
    # Offload blocking code to a thread
    result = await asyncio.to_thread(blocking_function, args)
    return result
```

### 3. Hybrid Approach
```python
async def process_data():
    # Parallelize CPU work with InterpreterPoolExecutor()
    with InterpreterPoolExecutor() as executor:
        cpu_results = await asyncio.to_thread(
            executor.map, cpu_task, inputs
        )
    # Async I/O
    await async_io-task(cpu_results)
```

## Dependency Compatibility
1. **Check SDKs for thread safety**:
```bash
# Find non-owned blocking imports outside thread_pool.py
rg -r 'import ' src/ | grep -v 'core/thread_pool.py'
```
2. **Verify existing `run_in_thread()` usage**:
```python
# Ensure wrappers handle thread safety
async def my_async_func():
    result = await run_in_thread(blocking_call)
    return result
```
3. **Update `pyproject.toml` if needed**:
```toml
[tool.uv]
python_version = "3.14"
```

## FAQs

### Q: Can I mix `InterpreterPoolExecutor` with async code?
**A:** Yes, but use `asyncio.to_thread` to bridge async and threaded code.

### Q: How do I test free-threaded code?
**A:** Use `pytest-asyncio` and mock thread-bound operations.

### Q: What about the GIL?
**A:** Free-threading bypasses the GIL for CPU-bound work but doesn't remove it entirely. Async still requires GIL management.


**Related References:**
- [Async patterns](../../python/brunofaust-python-style/references/async-patterns.md)
- [Thread safety guard hook](../../hooks/python-thread-subprocess-guard.py)
