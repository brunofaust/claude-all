# Python 3.14 Free-Threading Reference

## Overview
Python 3.14 introduces **free-threading**, allowing async code to leverage true parallelism under certain conditions. This feature is particularly relevant when using `asyncio` with `TaskGroup` for concurrent I/O operations.

## Use Cases
- **High-concurrency I/O Servers:** Web servers handling thousands of simultaneous connections.
- **Data Processing Pipelines:** Parallel processing of large datasets with I/O wait times.

## Pros & Cons
| **Pros** | **Cons** |
|----------|----------|
| Improved concurrency for I/O-bound tasks | Increased complexity in managing shared state |
| Better utilization of multi-core systems | Potential for subtle bugs if not properly synchronized |

## Implementation Example
```python
import asyncio

async def main():
    async with asyncio.TaskGroup() as tg:
        tg.create_task(io_bound_task("Task 1"))
        tg.create_task(io_bound_task("Task 2"))

async def io_bound_task(task_name):
    # Simulate I/O wait
    await asyncio.sleep(1)
    print(f"{task_name} completed")

# Run with Python 3.14+ to utilize free-threading
```

## Dependency Compatibility
Check `pyproject.toml` for version constraints:
```toml
[project]
# Ensure dependencies support Python 3.14
requires = [
    "python >=3.14",
    # Other dependencies...
]
```
