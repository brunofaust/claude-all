# Async + concurrency — full reference

... (existing content up to Structured Concurrency)

### InterpreterPoolExecutor (Python 3.14+ free-thread)

**When to use:** CPU-bound pure Python work requiring true parallelism

**Implementation example:**
```python
from concurrent.futures import InterpreterPoolExecutor

def cpu_bound_task(x: int) -> int:
    return x * x  # Pure Python computation

with InterpreterPoolExecutor() as executor:
    results = list(executor.map(cpu_bound_task, range(1000)))
```

**Key Considerations:**
- Tasks must be **stateless** or use synchronization (e.g., `threading.Lock`)
- Arguments and return values must be **picklable**
- **C extensions** may not work correctly across subinterpreters
- **GIL Note:** Each subinterpreter has its own GIL, but they can run in parallel

## Migration from ProcessPoolExecutor
```python
# Old (higher overhead)
with ProcessPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(cpu_bound_task, data))

# New (preferred for Python 3.14+ pure-Python CPU work)
with InterpreterPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(cpu_bound_task, data))
```

## Limitations
- **Shared State:** Requires explicit synchronization
- **Pickling:** Restricts complex object usage
- **C Extensions:** Some may not work correctly

## Compatibility Check
Ensure Python version and dependencies support free-thread execution:
```python
import sys

def require_free_thread_support():
    if sys.version_info < (3, 14):
        raise RuntimeError("free-thread requires Python 3.14+")

require_free_thread_support()
```

... (remainder of existing content unchanged)
