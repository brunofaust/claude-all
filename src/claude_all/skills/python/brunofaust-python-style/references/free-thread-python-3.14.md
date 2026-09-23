# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces free-threaded builds (PEP 703) where the Global Interpreter Lock (GIL) is disabled, allowing true parallelism across multiple threads for Python code. This is distinct from the existing `InterpreterPoolExecutor` (PEP 734) which uses subinterpreters for isolation.

Free-threading allows multiple threads to run Python bytecode simultaneously without the GIL bottleneck, while subinterpreters provide isolation with separate GILs per interpreter.

Key points:
- Free-threading builds are available as an experimental feature in Python 3.14
- Requires building Python with `--disable-gil` flag
- Extension modules must be updated to be thread-safe (use per-thread state or external locking)
- Pure Python code automatically benefits from free-threading when run in a free-threaded build

## When to Use

Free-threading is beneficial for:
- **CPU-bound pure Python workloads** that can be parallelized across threads
- **Workloads with frequent thread switching** where the GIL was a bottleneck
- **Scenarios where subinterpreter isolation is too restrictive** (need to share objects between threads)

Avoid free-threading for:
- **I/O-bound workloads** (use `async/await` + `run_in_thread()` instead)
- **CPU-bound C extensions** that release the GIL (these already run in parallel with `run_in_thread()`)
- **Code that relies on thread-unsafe C extensions** (may cause crashes or data corruption)

## Pros and Cons

### Pros
- True parallelism for pure Python code (no GIL bottleneck)
- Lower memory overhead compared to process-based parallelism
- Simpler sharing of objects between threads (no pickling/unpickling needed)
- Faster context switching than processes
- Compatible with existing `threading` module APIs

### Cons
- Requires free-threaded Python build (not available in standard distributions)
- Extension modules must be updated for thread safety
- Shared mutable state requires explicit synchronization (locks, atomics)
- Debugging race conditions is more complex
- Not all third-party packages are compatible yet
- Slight performance overhead for single-threaded code due to lock removal

## Implementation

### Basic Usage

Free-threading is enabled at the Python build level. To use it in your code:

```python
import threading
import sys

def cpu_bound_work(data):
    """CPU-bound pure Python function."""
    result = 0
    for item in data:
        result += hash(item)  # Simulate CPU work
    return result

def parallel_process(data_list, num_threads=4):
    """Process data in parallel using free-threading."""
    chunk_size = len(data_list) // num_threads
    threads = []
    results = [None] * len(data_list)

    def worker(start, end, index):
        results[index] = cpu_bound_work(data_list[start:end])

    for i in range(num_threads):
        start = i * chunk_size
        end = (i + 1) * chunk_size if i < num_threads - 1 else len(data_list)
        thread = threading.Thread(target=worker, args=(start, end, i))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    return results

# Check if running in free-threaded build
if sys._is_gil_enabled():
    print("Warning: Running with GIL enabled - free-threading not active")
else:
    print("Running in free-threaded build - true parallelism available")
```

### Hybrid CPU + I/O Workloads

For workloads that combine CPU-bound pure Python with I/O operations:

```python
import asyncio
import threading
import sys
from concurrent.futures import ThreadPoolExecutor

async def hybrid_workload(items):
    """Process items with CPU work and I/O in parallel."""
    # Check if free-threading is available
    free_threaded = not sys._is_gil_enabled()

    # CPU-bound work benefits from free-threading
    def cpu_process(item):
        # Simulate CPU-intensive work
        return sum(hash(str(item)) for _ in range(1000))

    # I/O-bound work (use existing patterns)
    async def io_process(item):
        # Simulate I/O operation
        await asyncio.sleep(0.01)
        return f"processed_{item}"

    # Process items
    if free_threaded:
        # Use free-threading for CPU work
        with ThreadPoolExecutor(max_workers=4) as executor:
            cpu_futures = [
                executor.submit(cpu_process, item)
                for item in items
            ]
            cpu_results = [f.result() for f in cpu_futures]
    else:
        # Fallback to existing run_in_thread for CPU work
        from myapp.core.thread_pool import run_in_thread
        cpu_results = []
        for item in items:
            result = await run_in_thread(cpu_process, item)
            cpu_results.append(result)

    # I/O work can run async regardless
    io_results = await asyncio.gather(*[io_process(item) for item in items])

    # Combine results
    return list(zip(cpu_results, io_results))

# Usage
# asyncio.run(hybrid_workload(items))
```

### Integration with Existing Patterns

When free-threading is available, you can choose between:
- **Free-threading threads**: For CPU-bound pure Python that needs to share objects
- **InterpreterPoolExecutor**: For CPU-bound pure Python that can tolerate isolation
- **run_in_thread()**: For I/O-bound work or C extensions that release the GIL

```python
import sys
from concurrent.futures import InterpreterPoolExecutor
from myapp.core.thread_pool import run_in_thread

def choose_execution_method(func, *args, is_cpu_bound=True, needs_sharing=False):
    """Choose the best execution method based on workload and free-threading availability."""
    free_threaded = not sys._is_gil_enabled()

    if is_cpu_bound:
        if free_threaded and needs_sharing:
            # Use free-threading threads for shared state
            import threading
            # ... implement thread-based execution
        elif free_threaded:
            # Use free-threading or InterpreterPoolExecutor
            # InterpreterPoolExecutor provides isolation without GIL
            with InterpreterPoolExecutor() as executor:
                return executor.submit(func, *args).result()
        else:
            # Fallback to thread pool for CPU work
            return run_in_thread(func, *args)
    else:
        # I/O-bound work: use run_in_thread
        return run_in_thread(func, *args)
```

## Dependency Compatibility

Checking dependency compatibility is crucial before deploying with free-threading.

### Compatibility Checklist

1. **Python Build**
   - Verify you're running a free-threaded Python build:
     ```python
     import sys
     free_threaded = not sys._is_gil_enabled()
     ```

2. **Pure Python Dependencies**
   - Most pure Python packages work automatically
   - Test for race conditions in shared state usage

3. **C Extension Dependencies**
   - Check if extensions are updated for free-threading:
     - Look for `Py_GIL_DISABLED` macro usage in source
     - Check documentation for free-threading support
     - Test thoroughly with concurrent access
   - Extensions that release the GIL (like NumPy, Pandas) are safe but won't see parallelism gains from free-threading

4. **Third-Party Packages**
   - Consult package documentation for free-threading support
   - Popular packages status (as of Python 3.14):
     - **Safe**: Pure Python packages, packages that release GIL during blocking ops
     - **Requires verification**: Packages with C extensions that hold internal state
     - **Unsafe**: Packages that assume GIL protection for internal data structures

5. **Internal Modules**
   - Audit for shared mutable state without proper locking
   - Use thread-local storage (`threading.local()`) where appropriate
   - Protect shared resources with locks (`threading.Lock`, `threading.RLock`)
   - Consider using atomic operations from `threading` module for simple counters

### Testing Strategy

1. **Unit Tests**
   - Run existing test suite with free-threaded build
   - Add concurrency-stress tests for critical sections
   - Use `threading` module to create multiple threads accessing shared resources

2. **Integration Tests**
   - Test typical workloads with multiple concurrent threads
   - Verify correctness of shared state updates
   - Check for performance improvements vs. threaded baseline

3. **Performance Benchmarks**
   - Compare free-threading vs. GIL-enabled threading
   - Compare free-threading vs. InterpreterPoolExecutor for CPU work
   - Measure overhead of locking mechanisms

### Migration Steps

1. **Verify Environment**
   ```bash
   python -c "import sys; print('Free-threaded:', not sys._is_gil_enabled())"
   ```

2. **Update Dependencies**
   - Check `pyproject.toml` or `requirements.txt` for compatible versions
   - Prefer packages with explicit free-threading support

3. **Run Tests**
   ```bash
   # Run with free-threaded Python
   prek run --all-files
   ```

4. **Monitor in Production**
   - Watch for increased CPU utilization (indicating parallelism)
   - Monitor for race conditions or data corruption
   - Track performance metrics before/after enabling

## Related Documentation

- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
- Consult `SKILL.md` for high-level skill conventions and recommendations
