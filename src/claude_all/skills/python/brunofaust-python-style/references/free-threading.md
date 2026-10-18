# Free-threading (PEP 703) — Python 3.14+

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use Free-threading

Free-threading (also known as "no-GIL" mode) is beneficial when:

1. **CPU-bound pure Python workloads** - When you have computationally intensive Python code that would benefit from true parallelism across multiple cores
2. **Multi-threaded applications** - Applications that currently use threading but are limited by the GIL
3. **Scientific computing and data processing** - Numerical computations, simulations, and data transformations
4. **When migrating from multiprocessing** - When you want to avoid the overhead of process creation and IPC
5. **Library development** - When building libraries that will benefit from parallel execution in consumer applications

**Do NOT use free-threading when:**
- You rely on thread-safety assumptions that were only valid with the GIL
- Your dependencies are not free-threading compatible
- You need deterministic single-threaded behavior for debugging/reproducibility
- Your workload is primarily I/O bound (asyncio is still better for this)

## Pros and Cons

### Pros:
- **True parallelism** - Multiple Python threads can execute Python bytecode simultaneously
- **Lower overhead** - Compared to multiprocessing, threads share memory space
- **Easier migration** - From existing threaded code vs. rewriting for multiprocessing
- **Better utilization** - Of multi-core CPUs for Python workloads
- **Compatible with existing threading APIs** - No need to change threading code structure

### Cons:
- **Dependency compatibility** - Many C extensions may not be thread-safe without the GIL
- **Potential race conditions** - Existing code may have hidden threading assumptions
- **Performance overhead** - Fine-grained locking can slow down single-threaded code
- **Debugging complexity** - Race conditions and non-deterministic behavior
- **Memory usage** - No change from threading, but higher than asyncio for I/O-bound work

## How to Implement Free-threading

### 1. Building Python 3.14 with Free-threading Support

Free-threading is available as a special build of Python 3.14:
```bash
# Download and compile Python 3.14 with --enable-free-threading
./configure --enable-free-threading --with-ensurepip=install
make -j$(nproc)
sudo make altinstall
```

### 2. Checking if You're Running Free-threading Build

```python
def is_freethreading_build():
    """Check if running in free-threading mode."""
    import sysconfig
    return sysconfig.get_config_var('Py_GIL_DISABLED') != 0

print(f"Free-threading build: {is_freethreading_build()}")
```

### 3. Basic Usage Patterns

Free-threading works with standard threading APIs:
```python
import threading
import time

def worker(n):
    result = 0
    for i in range(n):
        result += i * i
    return result

# Create and start threads
threads = []
results = []

def worker_with_result(n, result_list):
    result_list.append(worker(n))

for i in range(4):
    result = []
    thread = threading.Thread(target=worker_with_result, args=(1000000, result))
    threads.append(thread)
    result.append(result)  # Store reference to capture result
    thread.start()

# Wait for completion
for thread in threads:
    thread.join()

print(f"Results: {[r[0] for r in results]}")
```

### 4. Using with concurrent.futures

```python
from concurrent.futures import ThreadPoolExecutor
import math

def is_prime(n):
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

# With free-threading, this actually runs in parallel
with ThreadPoolExecutor(max_workers=4) as executor:
    numbers = [1000000000000000 + i for i in range(20)]
    results = list(executor.map(is_prime, numbers))

print(f"Prime results: {results}")
```

### 5. Library Author Considerations

If you're maintaining a C extension or library:
```c
// In your module initialization, check for free-threading support
#include <Python.h>

#if defined(Py_GIL_DISABLED) && Py_GIL_DISABLED
// Free-threading build - ensure your extension is thread-safe
// Use appropriate locking mechanisms for shared state
#else
// Regular build with GIL - existing thread safety assumptions apply
#endif

// Example of thread-safe counter in free-threading build
static int shared_counter = 0;
#if defined(Py_GIL_DISABLED) && Py_GIL_DISABLED
#include <pthread.h>
static pthread_mutex_t counter_mutex = PTHREAD_MUTEX_INITIALIZER;
#endif

static PyObject* increment_counter(PyObject* self, PyObject* args) {
#if defined(Py_GIL_DISABLED) && Py_GIL_DISABLED
    pthread_mutex_lock(&counter_mutex);
#endif
    shared_counter++;
    int result = shared_counter;
#if defined(Py_GIL_DISABLED) && Py_GIL_DISABLED
    pthread_mutex_unlock(&counter_mutex);
#endif
    return PyLong_FromLong(result);
}
```

## Checking Dependency Compatibility

### 1. Runtime Checks

```python
import sys
import threading
import time

def test_thread_safety():
    """Simple test to check if basic threading works."""
    counter = 0
    lock = threading.Lock() if hasattr(threading, 'Lock') else None

    def increment():
        nonlocal counter
        for _ in range(1000):
            if lock:
                with lock:
                    counter += 1
            else:
                counter += 1  # Not safe without GIL or explicit locking

    threads = [threading.Thread(target=increment) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # With proper locking, should be 10000
    # Without locking in free-threading, will be less
    return counter

# Run test
result = test_thread_safety()
print(f"Counter result: {result} (expected 10000 with proper locking)")
```

### 2. Checking Specific Dependencies

```python
import sys

def check_dependency_freethreading_compatibility():
    """Check if common dependencies support free-threading."""
    dependencies = {
        'numpy': 'Numerical computing',
        'pandas': 'Data manipulation',
        'orjson': 'JSON parsing',
        'polars': 'DataFrame library',
        'xxhash': 'Hashing',
        'cachebox': 'Caching',
        'structlog': 'Logging',
        'aiobotocore': 'AWS SDK',
        'uvloop': 'Event loop',
        'pydantic': 'Data validation',
    }

    results = {}
    for dep, description in dependencies.items():
        try:
            __import__(dep)
            # Try to check if module has free-threading info
            module = sys.modules[dep]
            ft_support = getattr(module, '__freethreading_compatible__',
                               getattr(module, '_freethreading_safe', 'unknown'))
            results[dep] = {
                'available': True,
                'description': description,
                'freethreading_support': ft_support
            }
        except ImportError as e:
            results[dep] = {
                'available': False,
                'description': description,
                'error': str(e)
            }
        except Exception as e:
            results[dep] = {
                'available': True,
                'description': description,
                'error': f"Import succeeded but check failed: {e}"
            }

    return results

# Print results
for dep, info in check_dependency_freethreading_compatibility().items():
    if info['available']:
        print(f"{dep}: {info['description']} - FT Support: {info.get('freethreading_support', 'unknown')}")
    else:
        print(f"{dep}: {info['description']} - NOT AVAILABLE: {info['error']}")
```

### 3. Community Resources

- **Python Wiki**: https://wiki.python.org/moin/PEP%20703
- **Free-threading Discussions**: https://discuss.python.org/c/core-dev/12
- **Compatibility Tracking**: https://github.com/python/cpython/issues/104522
- **PEP 703 Documentation**: https://peps.python.org/pep-0703/

### 4. Testing Strategy for Free-threading

1. **Unit Tests**: Run existing test suite with free-threading build
2. **Stress Tests**: Increase thread count and iteration counts
3. **Race Condition Detection**: Use tools like `threadsanitizer` if available
4. **Performance Benchmarks**: Compare single-threaded vs multi-threaded performance
5. **Dependency Validation**: Test each dependency individually and in combination

## Migration Guidelines

### From GIL-bound Threading:
1. Audit code for shared state without proper locking
2. Replace `threading.Lock()` with appropriate synchronization primitives
3. Test thoroughly for race conditions
4. Consider using `threading.RLock()` for reentrant locks
5. Use `threading.Condition()` for complex coordination

### From Multiprocessing:
1. Evaluate if shared memory requirements can be met with threads
2. Replace `ProcessPoolExecutor` with `ThreadPoolExecutor` where appropriate
3. Remove pickle/unpickle overhead for data sharing
4. Consider memory usage differences (threads share memory, processes don't)
5. Test for decreased startup time and improved latency

### From AsyncIO:
1. Free-threading is NOT a replacement for asyncio in I/O-bound scenarios
2. Use free-threading for CPU-bound components within async applications
3. Consider hybrid approaches: asyncio for I/O, threads for CPU work
4. Remember that blocking calls still block threads (use proper thread pools)

## Best Practices

1. **Start Small**: Enable free-threading for specific components first
2. **Monitor Performance**: Profile both single-threaded and multi-threaded performance
3. **Use Proper Synchronization**: Don't assume the GIL protects you anymore
4. **Test Extensively**: Pay special attention to edge cases and timing-dependent bugs
5. **Document Assumptions**: Clearly mark which parts of your code are free-threading aware
6. **Consider Hybrid Approaches**: Use free-threading for CPU work, asyncio for I/O
7. **Stay Updated**: Follow Python core developments and dependency compatibility updates

## When to Wait

Consider waiting to adopt free-threading if:
- Your critical dependencies don't yet support it
- You cannot invest in thorough testing for race conditions
- Your application is primarily I/O bound (stick with asyncio)
- You need deterministic behavior for financial or safety-critical systems
- Your team lacks experience with concurrent programming debugging

Free-threading in Python 3.14 represents a significant step toward true parallelism in Python, but requires careful consideration and testing to use effectively.
