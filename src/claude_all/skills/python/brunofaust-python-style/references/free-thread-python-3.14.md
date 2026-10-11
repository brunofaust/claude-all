# Python 3.14 Free-Threading — Reference Guide

## Overview

Python 3.14 introduces free-threading mode, which makes the Global Interpreter Lock (GIL) per-interpreter instead of global. This allows multiple interpreters to run Python code in parallel on multiple cores. The feature is enabled via the `PYTHONFREETHREADING=1` environment variable or by building Python with the `--disable-gil` flag.

In free-threading mode, the standard `threading` module can achieve true parallelism for CPU-bound Python code. However, extension modules must be updated to be compatible with free-threading.

The `interpreters` module (PEP 734) provides `InterpreterPoolExecutor` for running tasks in separate interpreters, which is the recommended way to use free-threading in the brunofaust-python-style skill.

## When to Use

Use free-threading for CPU-bound pure Python workloads that can be parallelized across multiple cores. Examples include:
- Data processing pipelines with pure Python transformations
- Scientific computing simulations
- Image processing algorithms implemented in pure Python

For I/O-bound workloads or workloads that rely on C extensions, continue to use the established patterns:
- I/O-bound: `async/await` + `run_in_thread()` for blocking operations
- CPU-bound C extensions: `run_in_thread()` (these already release the GIL effectively)

## Pros and Cons

### Pros
- True parallelism for CPU-bound Python code without the need for multiprocessing
- Lower memory overhead compared to multiprocessing (no need to pickle data between processes)
- Ability to share mutable state between interpreters when using high-level sharing APIs (though this is generally discouraged)
- Compatibility with the existing `threading` module API (though with new considerations)

### Cons
- Increased complexity in managing shared state and avoiding race conditions
- Extension modules must be updated to be free-threading compatible; many may not be initially
- Potential for increased memory usage if not careful with object sharing
- Debugging concurrent code is more challenging
- The free-threading mode may have different performance characteristics than the default GIL mode

## How to Implement

### Basic Usage with InterpreterPoolExecutor

```python
import concurrent.futures
import interpreters  # Python 3.14+

def cpu_bound_task(data):
    # Pure Python CPU-bound computation
    result = 0
    for item in data:
        result += heavy_computation(item)
    return result

def process_data_parallel(data_list):
    with interpreters.InterpreterPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(cpu_bound_task, chunk) for chunk in data_list]
        results = [f.result() for f in futures]
    return results
```

### Hybrid Approach (CPU + I/O)

For workloads that combine CPU-bound pure Python with I/O or C extensions, combine free-threading with the existing `run_in_thread()` pattern:

```python
import asyncio
import interpreters
from app.utils import run_in_thread  # Assuming this is the project's wrapper for blocking calls

async def hybrid_workflow(data):
    # Step 1: CPU-bound pure Python processing (use free-threading)
    with interpreters.InterpreterPoolExecutor(max_workers=2) as executor:
        cpu_future = executor.submit(cpu_bound_preprocessing, raw_data)
        # Step 2: I/O-bound operation (use run_in_thread to avoid blocking the event loop)
        io_future = run_in_thread(external_io_operation, raw_data)
        # Wait for both
        cpu_result = cpu_future.result()
        io_result = await io_future

    # Step 3: More CPU-bound work
    with interpreters.InterpreterPoolExecutor(max_workers=2) as executor:
        result_future = executor.submit(final_processing, cpu_result, io_result)
        return result_future.result()
```

### Important Considerations
- Only pure Python code and compatible extension modules can run in parallel in free-threading mode
- Arguments and return values passed between interpreters must be picklable (unless using high-level sharing APIs)
- Avoid sharing mutable state between interpreters without proper synchronization
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms (e.g., `threading.Thread` and `ThreadPoolExecutor` are banned in favor of `run_in_thread()` and `InterpreterPoolExecutor`)

## Dependency Compatibility

To check if your dependencies are compatible with free-threading:

1. **Pure Python packages**: Generally compatible, but check for any use of thread-sensitive globals or C extensions via ctypes.
2. **C extension modules**: Must be updated to use the new per-interpreter GIL API. Look for:
   - Documentation mentioning free-threading or "disable-gil" support
   - Wheels tagged with `abi3` and compatible with Python 3.14 free-threading
   - Explicit support statements from the maintainers
3. **Internal modules**: Review any C extensions or use of the Python C API for thread safety.
4. **Testing strategy**:
   - Run your test suite with `PYTHONFREETHREADING=1` to identify issues
   - Use `isolated` mode in pytest to check for state leakage between tests
   - Monitor for crashes, deadlocks, or incorrect results that indicate thread safety problems
5. **Resources**:
   - The Python 3.14 "What's New" document details the free-threading changes
   - The `interpreters` module documentation (PEP 734)
   - PEP 684 (per-interpreter GIL) and PEP 734 (interpreter pools)

## Related Documentation

- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
- Consult `SKILL.md` for high-level skill conventions and recommendations
