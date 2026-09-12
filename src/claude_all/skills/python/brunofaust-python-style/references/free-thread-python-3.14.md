# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces a free-threading mode (`PYTHON_GIL=0`) that disables the Global Interpreter Lock, enabling multiple threads to execute Python bytecode in parallel. This is different from the traditional behavior where the GIL ensures only one thread executes Python bytecode at a time.

Key mechanisms:
- **InterpreterPoolExecutor** (from `concurrent.futures`): Uses subinterpreters for true parallelism without the GIL
- **Existing `run_in_thread()`**: Continues to work for blocking I/O and C extensions that release the GIL

## When to Use Free-Threading

Free-threading is beneficial for:
- CPU-bound pure Python workloads that can be parallelized
- Workloads where the overhead of process creation (multiprocessing) is too high
- Scenarios requiring shared memory between threads (though with caveats)

Not recommended for:
- I/O-bound workloads (use `async/await` + `run_in_thread()` instead)
- Workloads heavily dependent on C extensions that don't support subinterpreters
- Simple scripts where complexity outweighs benefits

## Pros and Cons

### Advantages
- True parallelism for CPU-bound Python code
- Lower memory overhead compared to multiprocessing
- Shared memory space between threads (with proper synchronization)
- Compatible with existing `threading` module code (when run in free-threading mode)

### Disadvantages
- Requires Python 3.14+
- Not all C extensions are compatible with subinterpreters
- Shared mutable state requires explicit synchronization (locks, etc.)
- Only picklable objects can be passed between subinterpreters in InterpreterPoolExecutor
- Debugging complexity increases with true parallelism

## How to Implement

### Basic Usage with InterpreterPoolExecutor
```python
from concurrent.futures import InterpreterPoolExecutor
import math

def cpu_bound_work(n):
    """CPU-intensive function that works with free-threading."""
    return sum(math.isqrt(i) for i in range(n))

def parallel_cpu_work():
    with InterpreterPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(cpu_bound_work, 1000000) for _ in range(8)]
        results = [f.result() for f in futures]
    return sum(results)
```

### Hybrid Approach (CPU + I/O)
```python
import asyncio
from concurrent.futures import InterpreterPoolExecutor
from claude_all.hooks.python-thread-subprocess-guard import run_in_thread

async def hybrid_workflow():
    """Example showing both free-threading CPU work and I/O offloading."""
    # CPU-bound work with free-threading
    with InterpreterPoolExecutor(max_workers=2) as executor:
        cpu_future = executor.submit(cpu_bound_work, 500000)

        # I/O work offloaded to thread pool (for C extensions, file I/O)
        io_future = asyncio.get_event_loop().run_in_executor(
            None, run_in_thread, blocking_io_operation
        )

        cpu_result = await asyncio.wrap_future(cpu_future)
        io_result = await io_future

    return cpu_result, io_result

def blocking_io_operation():
    """Example blocking I/O operation (e.g., file read, database query)."""
    # This would be a real blocking operation
    pass
```

## Checking Dependency Compatibility

Before enabling free-threading, verify your dependencies are compatible:

### 1. Pure Python Dependencies
- Most pure Python packages work automatically with free-threading
- Test your specific use cases for thread safety

### 2. C Extension Dependencies
Check if C extensions support subinterpreters:
```python
import sys
import ctypes

def extension_supports_subinterpreters(module_name):
    """Check if a C extension module supports subinterpreters."""
    try:
        module = __import__(module_name)
        # Check for module-level attribute indicating compatibility
        return getattr(module, 'PyMod_INIT_RETURN_SUCCESS', False) or \
               hasattr(module, 'm_def') and module.m_def.m_base.m_size > 0
    except ImportError:
        return False

# Example usage:
# if extension_supports_subinterpreters('numpy'):
#     print("NumPy supports subinterpreters")
# else:
#     print("NumPy may not support subinterpreters - test carefully")
```

### 3. Project-Specific Guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
- Consult `SKILL.md` for high-level skill conventions and recommendations

## Related Documentation
- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
- Consult `SKILL.md` for high-level skill conventions and recommendations
