# free-thread — Python 3.14's free-thread feature
## Overview
Python 3.14 introduced the `InterpreterPoolExecutor` which allows for true parallelism by leveraging subinterpreters, addressing the Global Interpreter Lock (GIL) limitations for CPU-bound tasks.

## When to Use
- **CPU-bound tasks**: Utilize `InterpreterPoolExecutor` for parallel execution where multiple cores can be leveraged (e.g., data processing, machine learning, image processing).
- **I/O-bound tasks**: Continue using `asyncio` with `run_in_thread()` for blocking I/O operations.

## Pros and Cons
### Pros
- **True Parallelism**: Execute Python code in parallel across multiple CPU cores.
- **PEP 695 Compliance**: Native support in Python 3.14+ for type parameters.
- **Simplified Concurrency**: Easier to reason about compared to threading with locks.

### Cons
- **GIL Limitations**: Still affected by the GIL for threads within a subinterpreter.
- **Memory Overhead**: Each subinterpreter has its own memory space.
- **Compatibility**: May not work with libraries that rely on the GIL.

## Implementation
1. **Use `InterpreterPoolExecutor`**:
   ```python
   from concurrent.futures import InterpreterPoolExecutor

   with InterpreterPoolExecutor() as executor:
       results = list(executor.map(my_cpu_bound_function, inputs))
   ```
2. **Avoid GIL-bound operations**: Ensure tasks are CPU-intensive and not I/O-bound.

## Dependency Compatibility
- **Check Library Support**: Ensure third-party libraries are compatible with Python 3.14+ and free-threading.
- **Test for Interoperability**: Verify that libraries don't rely on GIL-specific behaviors.
- **Update Dependencies**: If necessary, upgrade libraries to versions supporting free-thread.

## Testing
- **Unit Tests**: Use `unittest` or `pytest` with `InterpreterPoolExecutor` to validate parallel behavior.
- **Integration Tests**: Ensure tasks execute as expected in a parallel environment.
