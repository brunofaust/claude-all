=== Python 3.14 Free-Thread Feature Reference ===

=== Overview ===
Python 3.14 introduces the `InterpreterPoolExecutor`, enabling true parallelism by utilizing multiple sub-interpreters, thus bypassing the Global Interpreter Lock (GIL) for CPU-bound tasks.

=== When to Use ===
- **CPU-bound pure Python workloads** (e.g., mathematical computations, data processing with Pandas)
- **Embarassingly parallel tasks** (e.g., independent data transformations, batch processing)

=== Pros and Cons ===
| ""|""|
|---|---|
| True parallelism within a single process | Limited to picklable arguments/results
| Lower overhead compared to `ProcessPoolExecutor` | No shared mutable state between sub-interpreters
| Native integration with `asyncio` | C extensions may not work as expected

=== Implementation Example ===
```python
from concurrent.futures import InterpreterPoolExecutor

# Correct usage for CPU-bound tasks
import numpy as np

def compute_square(x: int) -> int:
    """
    CPU-bound computation
    """
    return x * x

async def main():
    with InterpreterPoolExecutor() as executor:
        results = list(executor.map(compute_square, range(100)))
    return results
```

=== Dependency Compatibility ===
- **Python Version**: Ensure Python 3.14 or later
- **Library Checks**: Use `if sys.version_info >= (3, 14)` guards
- **Type Handling**: Be cautious with non-picklable types (e.g., database connections, file handles)

=== Integration with Existing Patterns ===
For blocking I/O or shared state, continue using `run_in_thread` as described in `async-patterns.md`.

=== Further Reading ===
Refer to `async-patterns.md` for broader context on concurrency patterns in the project.
