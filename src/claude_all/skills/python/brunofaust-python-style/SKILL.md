## Core principles
1. **Python 3.14+** — pipe unions (`str | None`), `match` statements, `asyncio.TaskGroup`, `exception.add_note()`, `ExceptionGroup` / `except*`, **PEP 695** generics + type aliases (`type EntityId = str`, `def first[T](...)`, `class Stack[T]`), **PEP 758** paren-less `except ValueError, TypeError:`, **PEP 649** lazy annotations (no `from __future__ import annotations`).

## Python 3.14 Free-Thread Feature
**When to use:**
- For CPU-bound operations that can be parallelized using multiple threads.
- When leveraging Python 3.14's improved thread management and performance optimizations.

**Pros:**
- Improved performance for concurrent execution of CPU-bound tasks.
- Simplified threading model with better resource utilization.

**Cons:**
- Potential for increased memory usage due to multiple threads.
- Complexity in managing thread synchronization if not handled properly.

**Implementation:**
- Use `asyncio.TaskGroup` for structured concurrency.
- Leverage `concurrent.futures.ThreadPoolExecutor` for threading.
- Ensure thread safety with proper synchronization primitives if needed.

**Checking Dependency Compatibility:**
Refer to `REFERENCES/free-thread-guide.md` for detailed guidance on ensuring dependencies are compatible with Python 3.14's free-thread feature.
