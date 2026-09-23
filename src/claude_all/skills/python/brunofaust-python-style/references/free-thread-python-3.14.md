# Free-threading in Python 3.14 — reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces experimental free-threading support via PEP 703, making the Global Interpreter Lock (GIL) optional. When built with `--disable-gil`, Python threads can run in parallel on multiple cores, enabling true multi-threading for CPU-bound workloads without the overhead of process-based parallelism.

This feature is currently in experimental status and requires a special build of Python. The free-threading mode changes the threading model from cooperative (GIL-protected) to preemptive parallel execution.

## Use Cases

### When to Use Free-threading

Free-threading is beneficial for:

- **CPU-bound Python workloads** that currently use `ProcessPoolExecutor` or `multiprocessing`
- **Applications with heavy numerical computation**, data processing, or scientific computing
- **Workloads that need shared memory access** between threads (avoiding pickle overhead)
- **Gradual migration from multiprocessing to threading** where shared state is needed
- **High-concurrency I/O applications** where thread-per-connection models scale better

### When Not to Use

Avoid free-threading when:

- Using **C extensions that depend on GIL behavior** (many may need updates)
- Requiring **strict backward compatibility** with Python 3.13 and earlier
- Building **production systems** before the feature graduates from experimental status
- Working with **libraries that haven't been verified** for GIL-free compatibility

## Pros and Cons

### Advantages

| Benefit | Description |
|---------|-------------|
| **True parallelism** | Threads run concurrently on multiple cores without GIL contention |
| **Lower overhead** | No process creation/memory duplication like `multiprocessing` |
| **Shared memory** | Easy sharing of objects between threads without serialization |
| **Faster context switching** | Thread switches are cheaper than process switches |
| **Gradual adoption** | Can enable per-interpreter or per-module basis |

### Disadvantages

| Drawback | Description |
|----------|-------------|
| **Experimental status** | May have bugs, performance regressions, or missing features |
| **Extension compatibility** | Many C extensions need updates or may behave unexpectedly |
| **Debugging complexity** | Race conditions and thread safety issues become more likely |
| **Memory overhead** | Some internal structures may increase in size |
| **Limited tooling** | Profilers, debuggers, and analyzers may not fully support free-threading |

## Implementation

### Building Python with Free-threading

To use free-threading, you need a special build of Python 3.14:

```bash
# Clone Python source
git clone https://github.com/python/cpython.git
cd cpython
git checkout 3.14

# Configure with free-threading disabled (experimental)
./configure --disable-gil --prefix=/opt/python3.14-freet
make -j$(nproc)
make install
```

### Detecting Free-threading Support

At runtime, check if free-threading is enabled:

```python
import sys
import threading

def is_freethreading_enabled():
    """Check if Python is running with GIL disabled."""
    return hasattr(sys, '_is_gil_enabled') and not sys._is_gil_enabled()

# Alternative check
def has_free_threading():
    return hasattr(sysconfig, 'get_config_var') and \
           sysconfig.get_config_var('Py_GIL_DISABLED') == '1'

# Simple version check (less reliable)
def approx_freethreading():
    return sys.version_info >= (3, 14) and hasattr(sys, '_is_gil_enabled')
```

### Basic Usage Patterns

Free-threading works with standard threading APIs:

```python
import threading
import time

def cpu_bound_work(n):
    """CPU-intensive function that benefits from free-threading."""
    total = 0
    for i in range(n):
        total += i * i
    return total

def worker_thread(results, worker_id, iterations):
    """Worker function for threading."""
    result = cpu_bound_work(iterations)
    results[worker_id] = result
    print(f"Worker {worker_id} completed")

# Using free-threading
if is_freethreading_enabled():
    print("Running with free-threading enabled")
    
    results = [None] * 4
    threads = []
    
    for i in range(4):
        t = threading.Thread(target=worker_thread, args=(results, i, 1000000))
        t.start()
        threads.append(t)
    
    for t in threads:
        t.join()
    
    print(f"Results: {results}")
else:
    print("Running with GIL enabled - consider using InterpreterPoolExecutor")
```

### Using with concurrent.futures

The `ThreadPoolExecutor` automatically benefits from free-threading:

```python
from concurrent.futures import ThreadPoolExecutor
import math

def is_prime(n):
    """CPU-intensive prime check."""
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    for i in range(3, int(math.sqrt(n)) + 1, 2):
        if n % i == 0:
            return False
    return True

def find_primes_in_range(start, end):
    """Find primes in a given range."""
    return [n for n in range(start, end) if is_prime(n)]

# With free-threading enabled, this uses multiple cores
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [
        executor.submit(find_primes_in_range, i*10000, (i+1)*10000)
        for i in range(10)
    ]
    results = []
    for future in futures:
        results.extend(future.result())
    
    print(f"Found {len(results)} primes")
```

### Interoperability with Async Code

Free-threading works alongside async code:

```python
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

async def async_main():
    """Main async function that offloads CPU work to threads."""
    
    # CPU-bound function
    def heavy_computation(n):
        return sum(i*i for i in range(n))
    
    # Run CPU-bound work in thread pool (benefits from free-threading)
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Offload to thread pool
        result = await loop.run_in_executor(
            executor, heavy_computation, 1000000
        )
        print(f"Computation result: {result}")
    
    # Can also use asyncio.to_thread (benefits from free-threading)
    result2 = await asyncio.to_thread(heavy_computation, 500000)
    print(f"Second result: {result2}")

# Run the async program
if __name__ == "__main__":
    asyncio.run(async_main())
```

## Compatibility

### Checking Dependency Compatibility

To verify if your dependencies work with free-threading:

#### 1. Pure Python Dependencies
Pure Python packages generally work without modification since they don't interact directly with the GIL.

#### 2. C Extension Dependencies
C extensions need to be checked for GIL compatibility:

```python
import sys
import importlib

def check_extension_gil_safety(module_name):
    """Check if a C extension is likely safe for free-threading."""
    try:
        module = importlib.import_module(module_name)
        
        # Check if module has GIL-related attributes
        gil_safe_indicators = [
            hasattr(module, '__pyx_gil_use__'),  # Cython
            hasattr(module, '_is_gil_enabled'),  # Manual check
            # Many extensions don't expose this info directly
        ]
        
        # If we can't determine safety, assume it may need checking
        return True  # Optimistic assumption - verify through testing
        
    except ImportError:
        return False

# Example usage
extensions_to_check = ['numpy', 'pandas', 'polars', 'lxml', 'cryptographic']
for ext in extensions_to_check:
    if check_extension_gil_safety(ext):
        print(f"{ext}: Likely compatible (verify through testing)")
    else:
        print(f"{ext}: Not available or unknown compatibility")
```

#### 3. Testing Strategy

Create a test suite to validate compatibility:

```python
import unittest
import threading
import time
import sys

class FreeThreadingCompatibilityTest(unittest.TestCase):
    @unittest.skipIf(not hasattr(sys, '_is_gil_enabled') or sys._is_gil_enabled(),
                     "Free-threading not enabled")
    def test_shared_counter(self):
        """Test that shared counter works correctly with free-threading."""
        counter = {'value': 0}
        lock = threading.Lock()
        iterations = 10000
        
        def increment_counter():
            for _ in range(iterations):
                with lock:  # Still need locks for shared state
                    counter['value'] += 1
        
        threads = []
        for _ in range(4):
            t = threading.Thread(target=increment_counter)
            t.start()
            threads.append(t)
        
        for t in threads:
            t.join()
        
        # With proper locking, should be 4 * iterations
        self.assertEqual(counter['value'], 4 * iterations)
    
    @unittest.skipIf(not hasattr(sys, '_is_gil_enabled') or sys._is_gil_enabled(),
                     "Free-threading not enabled")
    def test_cpu_bound_scaling(self):
        """Test that CPU-bound work scales with thread count."""
        import math
        
        def cpu_work(n):
            # CPU-intensive work
            return sum(math.isqrt(i) for i in range(n))
        
        import concurrent.futures
        import time
        
        # Single threaded
        start = time.time()
        result1 = cpu_work(2000000)
        single_time = time.time() - start
        
        # Multi threaded
        start = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(cpu_work, 500000) for _ in range(4)]
            results = [f.result() for f in futures]
        multi_time = time.time() - start
        
        # Should show some scaling (exact ratio depends on system)
        # Allow for overhead - looking for at least 2x improvement on 4 cores
        self.assertLess(multi_time, single_time * 0.6)  # At least 1.66x speedup

# Run tests
if __name__ == '__main__':
    unittest.main()
```

### Known Incompatible Packages

As of Python 3.14 release, these categories of packages may need attention:

| Package Type | Risk Level | Notes |
|--------------|------------|-------|
| **Old C extensions** | High | May assume GIL protection for internal state |
| **GUI toolkits** | Medium | Often have threading assumptions |
| **Database drivers** | Low-Medium | Varies by implementation |
| **Cryptography libraries** | Medium | May have thread-safety assumptions |
| **Scientific computing** | Variable | NumPy, SciPy work on free-threading builds |

### Migration Guidelines

1. **Start with testing**: Run your test suite on a free-threading Python build
2. **Identify C extensions**: Use `sysconfig.get_config_var('EXT_SUFFIX')` to check extensions
3. **Add runtime checks**: Guard free-threading usage with version and capability checks
4. **Use gradual adoption**: Enable free-threading per-module or per-interpreter initially
5. **Monitor performance**: Profile to ensure you're getting expected benefits
6. **Fall back gracefully**: Have GIL-enabled paths for production stability

### Best Practices

1. **Still use locks for shared state**: Free-threading doesn't eliminate need for synchronization
2. **Prefer InterpreterPoolExecutor for isolation**: When you don't need shared memory
3. **Test thoroughly**: Race conditions may appear that never occurred with GIL
4. **Monitor memory usage**: Some internal structures may be larger
5. **Consider hybrid approaches**: Use free-threading where beneficial, GIL where needed
6. **Keep dependencies updated**: Extension maintainers are adapting to free-threading

## Related Patterns

See `async-patterns.md` for:
- [`run_in_thread()`](#running-blocking-code-in-threads-run_in_thread) - for offloading blocking work
- [`InterpreterPoolExecutor`](#interpreterpoolexecutor) - alternative parallelism approach
- [Thread pool patterns](#thread-pool-manager-class) - managing thread pools effectively

## Further Reading

- [PEP 703 – Making the Global Interpreter Lock Optional in CPython](https://peps.python.org/pep-0703/)
- [Python 3.14 Free-threading Documentation](https://docs.python.org/3.14/c-api/gil.html)
- [Free-threading Wiki](https://wiki.python.org/moin/Gilectomy)