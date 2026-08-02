# Free-Thread Feature in Python 3.14

## Overview
Python 3.14 introduces the **free-thread** feature (PEP 695, PEP 758), enabling safer concurrent execution and improved performance. This document explains when to use it, its pros and cons, implementation strategies, and how to check dependency compatibility.

---

## When to Use

### Use Cases
- **High-concurrency applications**: Free-threading improves throughput in async I/O-bound workloads.
- **Resource-intensive tasks**: Leverages Python’s `asyncio.TaskGroup` for structured concurrency.
- **Legacy code migration**: Simplifies adoption of async patterns in existing codebases.

### Avoid When
- **CPU-bound work**: Use `run_in_thread()` or `InterpreterPoolExecutor` instead.
- **Strict compatibility**: Projects requiring Python <3.14.

---

## Pros and Cons

| **Pros** | **Cons** |
|-----------------------------------|-----------------------------------|
| Improved concurrency handling | Learning curve for async patterns |
| Better error handling (ExceptionGroup) | Requires careful resource management |
| Cleaner syntax (pipe unions, match) | Potential for deadlocks if misused |

---

## Implementation

### Key Patterns
1. **Structured Concurrency**
```python
async with asyncio.TaskGroup() as tg:
    tg.create_task(fetch_data())
    tg.create_task(process_data())
```

2. **Error Handling**
```python
except* (ValueError, TypeError) as eg:
    for e in eg.exceptions:
        logger.error(f"Validation failed: {e}")
```

3. **PEP 695 Generics**
```python
from collections.abc import Sequence

def first[T](items: Sequence[T]) -> T:
    ...
```

---

## Dependency Compatibility

1. **Check `pyproject.toml`**:
```toml
[project]
dependencies = [
    "requests = ^2.31.0",
    # Ensure all dependencies support Python 3.14
]
```

2. **Scan for Incompatibilities**
- Use `python-deps` skill to verify:
```claude-all --all --user python-deps
```

3. **Update Dependencies**
```bash
uv add package-name --upgrade
```

---

**Related References**:
- [async-patterns.md](async-patterns.md)
- [type-hints.md](type-hints.md)
- [error-handling.md](error-handling.md)
