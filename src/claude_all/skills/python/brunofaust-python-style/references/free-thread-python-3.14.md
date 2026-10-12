# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

- CPU-bound pure Python workloads that can benefit from parallelism without the GIL
- When you have true CPU-bound tasks (not just I/O-bound) and want to utilize multiple cores
- For workloads where InterpreterPoolExecutor (PEP 734) is suitable (picklable data, no shared mutable state)

## Pros and Cons

### Pros
- True parallelism for CPU-bound Python code (each interpreter has its own GIL)
- Lower overhead than ProcessPoolExecutor (no process creation, faster startup)
- Shared memory between interpreters for certain immutable types (str, bytes, int, float, bool, None, tuple, memoryview)
- Can be used alongside existing async patterns (async/await, run_in_thread)

### Cons
- Only picklable arguments/results can be shared between interpreters
- No shared mutable state (each interpreter is isolated)
- C extensions that rely on global state may not work correctly
- Requires Python 3.14+ (not available on older versions)
- Debugging and profiling tools may not yet support free-threading

## How to Implement

### Basic Usage with InterpreterPoolExecutor

```python
from concurrent.futures import InterpreterPoolExecutor

def compute_square(x: int) -> int:
    """CPU-bound computation."""
    return x * x

# Similar API to ThreadPoolExecutor / ProcessPoolExecutor
with InterpreterPoolExecutor() as executor:
    results = list(executor.map(compute_square, range(100)))
```

### Hybrid Approach (CPU + I/O)

For workloads that have both CPU-bound and I/O-bound components, you can combine free-threading with async patterns:

```python
import asyncio
from concurrent.futures import InterpreterPoolExecutor
from typing import Any

async def process_item(item: Any) -> Any:
    """Process a single item with both CPU and I/O components."""
    # CPU-bound computation (use free-threading)
    with InterpreterPoolExecutor() as executor:
        cpu_result = await asyncio.get_running_loop().run_in_executor(
            executor, compute_expensive_value, item
        )

    # I/O-bound operation (use async)
    io_result = await fetch_from_network(cpu_result)

    return io_result

async def compute_expensive_value(x: int) -> int:
    """CPU-bound function to run in free-thread."""
    # Simulate CPU work
    return x * x

async def fetch_from_network(value: int) -> dict[str, Any]:
    """Simulate I/O-bound network fetch."""
    await asyncio.sleep(0.1)  # Simulate network delay
    return {"value": value, "data": f"data_for_{value}"}

async def main():
    items = list(range(10))
    tasks = [process_item(item) for item in items]
    results = await asyncio.gather(*tasks)
    return results
```

## Checking Dependency Compatibility

To determine if your dependencies are compatible with free-threading:

1. **Check for C extensions**: Dependencies with C extensions may not work correctly if they rely on global state or assume a single GIL. Test thoroughly.
2. **Pure Python libraries**: These are generally compatible as long as they only use picklable data for communication between interpreters.
3. **Test your specific use case**: Run your test suite with the free-threading build of Python 3.14 (if available) to identify any issues.
4. **Consult documentation**: Check if the library explicitly supports free-threading or subinterpreters.
5. **Use the project's existing patterns**:
   - For CPU-bound pure Python: Prefer `InterpreterPoolExecutor` (when available) or free-threading
   - For CPU-bound C extensions or blocking I/O: Continue using `run_in_thread()` (these already release the GIL effectively)
   - Avoid sharing mutable state between interpreters

## Related Documentation

- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
- Consult `SKILL.md` for high-level skill conventions and recommendations
