# Python 3.14 Free-Thread Feature Reference

## Overview
The Python 3.14 free-thread feature (PEP 734) introduces the ability to run Python code in multiple subinterpreters, allowing true parallelism while maintaining compatibility with existing asyncio patterns.

## When to Use
- **CPU-bound workloads:** Use `InterpreterPoolExecutor` for parallel execution of pure-Python, CPU-intensive tasks.
- **Mixed I/O and CPU:** Combine with existing `run_in_thread` for I/O-bound tasks or blocking C extensions.

## Pros and Cons
| Pros | Cons |
|------|------|
| True parallelism for CPU work | Limited to picklable objects Only |
| Lower overhead than ProcessPoolExecutor | Shared state across subinterpreters requires care |

## Implementation Example
```python
from concurrent.futures import InterpreterPoolExecutor
import time

def compute_square(x: int) -> int:
    """CPU-bound computation."""
    time.sleep(0.1)  # Simulate work
    return x * x

async def main():
    with InterpreterPoolExecutor() as executor:
        results = list(executor.map(compute_square, range(100)))
    print(results)

if __name__ == "__main__":
    main()
```

## Dependency Compatibility
### Check 1: Pickling
Ensure all data passed to `InterpreterPoolExecutor` is picklable.
```python
import pickle

def test_pickling():
    obj = SomeClass()  # Replace with actual data
    pickle.dumps(obj)  # Should not raise

### Check 2: Shared State
Avoid sharing mutable global state across subinterpreters without synchronization.

### Check 3: C Extensions
Ensure C extensions used in the codebase properly release the GIL.

## Migration from `run_in_thread`
Replace `run_in_thread` usages for pure CPU work:
```python
# Before (thread pool)
result = await run_in_thread(some_cpu_bound_function, arg)

# After (subinterpreter pool)
with InterpreterPoolExecutor() as executor:
    result = executor.submit(some_cpu_bound_function, arg).result()
```

## Known Limitations
1. **Shared State:** Subinterpreters share memory, so non-thread-safe operations can lead to data races.
2. **Pickling:** Only picklable objects can be passed between interpreters.
3. **Overhead:** For I/O-bound or mixed workloads, `run_in_thread` may be more efficient.

## Follow-up Work
- Automated detection of non-picklable objects
- Guidance for safe shared state management
- Performance benchmarking suite comparing `InterpreterPoolExecutor`, `ProcessPoolExecutor`, and `run_in_thread`
