# Free-thread Python 3.14 Reference

## Overview
Python 3.14 introduces the free-thread feature (PEP 695) enabling true parallelism through interpreter subpools. This reference covers implementation patterns, pros/cons, and compatibility checks.

## When to Use
- **CPU-bound workloads** (e.g., data processing with Polars/Pandas)
- **Shared-nothing workloads** (no in-memory state sharing)
- **Pickler-friendly tasks** (args/results must be serializable)

## Key Concepts
- **InterpreterPoolExecutor**: Runs tasks in separate subinterpreters
- **Subinterpreters**: Independent execution contexts with shared GIL
- **Pickling**: Task arguments/results must be serializable

## Pros vs Cons
| Aspect | InterpreterPoolExecutor | ThreadPoolExecutor | ProcessPoolExecutor |
|-------|------------------------|--------------------|---------------------|
| GIL | Shared per subinterpreter | Shared | None (separate proc) |
| Memory | Shared | Shared | Separate |
| Overhead | Low (within Python) | Low | High (IPC) |
| State | Immutable shared state | Mutable shared state | No direct state access |
| Use Case | CPU-bound (no FFI) | I/O-bound | Heavy CPU (FFI ok) |

## Implementation Patterns
### Basic Usage
```python
from concurrent.futures import InterpreterPoolExecutor

def cpu_bound_task(x: int) -> int:
    return x * x

with InterpreterPoolExecutor() as executor:
    results = list(executor.map(cpu_bound_task, range(1000)))
```

### Migration from ProcessPoolExecutor
```python
# Old
with ProcessPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(cpu_bound_task, data))

# New
with InterpreterPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(cpu_bound_task, data))
```

### State Sharing
For shared state, use thread-safe containers:
```python
from concurrent.futures import InterpreterPoolExecutor
from typing import List
import threading

def task(index: int, shared_list: list, lock: threading.Lock) -> None:
    with lock:
        shared_list.append(index * 2)

if __name__ == "__main__":
    shared = []
    lock = threading.Lock()
    with InterpreterPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(task, i, shared, lock) for i in range(100)]
        concurrent.futures.wait(futures)
    print(f"Shared state: {shared}")
```

## Compatibility Checks
### Dependency Validation
Ensure all dependencies support free-thread execution:
1. **Check for GIL usage**: C extensions that release the GIL may not work correctly
2. **Serialization**: All task args/results must be picklable
3. **State mutation**: Avoid mutable shared state

### Runtime Check
```python
import sys

def require_free_thread_support():
    if sys.version_info < (3, 14):
        raise RuntimeError("free-thread requires Python 3.14+")

require_free_thread_support()
```

## Limitations
- **Shared state**: Requires synchronization primitives (locks)
- **Pickling**: Limits complex object usage
- **C extensions**: Some may not work correctly across subinterpreters

## Testing
### Unit Tests
```python
import pytest
from concurrent.futures import InterpreterPoolExecutor

def test_interpreter_pool():
    with InterpreterPoolExecutor() as executor:
        result = list(executor.map(lambda x: x * x, range(5))
    assert result == [0, 1, 4, 9, 16]
```

### Integration Tests
For CPU-bound workloads:
```python
import pandas as pd
from concurrent.futures import InterpreterPoolExecutor

def process_chunk(df: pd.DataFrame) -> pd.DataFrame:
    return df * 2

if __name__ == "__main__":
    with InterpreterPoolExecutor() as executor:
        dfs = [pd.read_csv("data.csv") for _ in range(4)]
        futures = [executor.submit(process_chunk, df) for df in dfs]
        results = [f.result() for f in concurrent.futures.wait(futures).done]
```

## When Not to Use
- **I/O-bound workloads** → use `run_in_thread()`
- **Mixed state mutation** → prefer `ThreadPoolExecutor`
- **Non-picklable args/results** → use alternative parallelism
