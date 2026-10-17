# Python 3.14 Free-Threading (No GIL) Guide

## When to Use Free-Threading

Consider enabling Python 3.14's free-threading mode when:

1. **CPU-bound workloads**: Applications that spend significant time in Python code (not waiting for I/O)
2. **Multi-core utilization**: When you need to truly parallelize CPU-intensive tasks across multiple cores
3. **Scientific computing**: Numerical computations, data processing, machine learning workloads
4. **High-concurrency services**: Servers handling many simultaneous requests that perform CPU-intensive work
5. **Replacing multiprocessing**: When you want to avoid the complexity and memory overhead of multiprocessing

Avoid free-threading for:
- Pure I/O-bound applications (web scrapers, API clients waiting on network)
- Applications heavily dependent on C extensions that aren't free-threading compatible
- Simple scripts where threading complexity isn't justified

## Pros and Cons

### Pros
- **True parallelism**: Multiple Python threads can run simultaneously on multiple cores
- **Lower memory overhead**: Compared to multiprocessing, threads share memory space
- **Simpler sharing**: Easy data sharing between threads without serialization/deserialization
- **Better integration**: Works with existing threading code patterns
- **Reduced complexity**: No need for inter-process communication mechanisms

### Cons
- **Extension compatibility**: C extensions must be updated to support free-threading
- **Potential for race conditions**: Existing code may have hidden threading bugs
- **Debugging complexity**: Concurrent bugs can be harder to reproduce and diagnose
- **Performance variability**: Some workloads may see slower performance due to increased locking overhead
- **Library ecosystem lag**: Not all popular libraries may be immediately compatible

## How to Implement Free-Threading

### Enabling Free-Threading Mode

Python 3.14 introduces a new build mode and runtime flag:

1. **Build Python with free-threading support**:
   ```bash
   ./configure --enable-free-threading
   make
   make install
   ```

2. **Run with free-threading enabled**:
   ```bash
   # Using environment variable
   PYTHONFREETHREADING=1 python3.14 your_script.py

   # Or using -X flag
   python3.14 -X freethreading your_script.py
   ```

### Code Considerations

When writing free-threading compatible code:

1. **Use threading primitives correctly**:
   ```python
   import threading
   from threading import Lock, RLock, Semaphore, BoundedSemaphore, Event, Condition

   # Protect shared resources with locks
   shared_counter = 0
   counter_lock = Lock()

   def increment_counter():
       global shared_counter
       with counter_lock:
           shared_counter += 1
   ```

2. **Prefer thread-safe data structures**:
   - Use `queue.Queue` for producer-consumer patterns
   - Consider `collections.deque` with appropriate locking
   - Use `threading.local()` for thread-local storage when needed

3. **Avoid global mutable state**:
   - Minimize shared mutable state between threads
   - Use immutable data structures when possible
   - Pass state explicitly rather than relying on globals

4. **Handle the GIL removal gracefully**:
   ```python
   import sys

   # Check if free-threading is enabled
   if hasattr(sys, 'is_freethreaded') and sys.is_freethreaded:
       # Free-threading specific optimizations or checks
       pass
   ```

### Migration Strategies

1. **Gradual adoption**:
   - Start with enabling free-threading in development/staging
   - Run test suite to identify threading issues
   - Fix race conditions and locking problems
   - Gradually roll out to production

2. **Hybrid approach**:
   - Keep critical sections protected with appropriate locks
   - Use free-threading for embarrassingly parallel tasks
   - Fall back to single-threaded mode for incompatible components

## Checking Dependency Compatibility

### Checking if Python is Free-Threading Enabled

```python
import sys

def is_freethreading_enabled():
    """Check if Python is running with free-threading enabled."""
    return hasattr(sys, 'is_freethreaded') and sys.is_freethreaded

# Usage
if is_freethreading_enabled():
    print("Running in free-threading mode")
else:
    print("Running with GIL enabled")
```

### Checking Extension Compatibility

1. **Manual inspection**:
   - Check if extensions were compiled with `Py_GIL_DISABLED` macro
   - Look for `PyUnstable_Thread*` API usage in source

2. **Runtime testing**:
   ```python
   import ctypes
   import sys

   def check_gil_status():
       """Check if GIL is disabled in current Python runtime."""
       if hasattr(sys, 'is_freethreaded'):
           return not sys.is_freethreaded  # Returns True if GIL is enabled
       return True  # Assume GIL enabled if attribute doesn't exist

   if check_gil_status():
       print("GIL is enabled")
   else:
       print("GIL is disabled (free-threading)")
   ```

3. **Library-specific checks**:
   - **NumPy**: Check if built with `NPY_DISABLE_GIL` (experimental)
   - **Pandas**: Monitor for free-threading support in future releases
   - **Orjson**: Check if using free-threading compatible build
   - **Uvloop**: Verify asyncio event loop compatibility

### Dependency Verification Process

1. **Create a compatibility test script**:
   ```python
   import concurrent.futures
   import threading
   import time
   import sys

   # Test basic threading behavior
   def cpu_bound_task(n):
       """Simple CPU-intensive task"""
       return sum(i * i for i in range(n))

   def test_threading_safety():
       """Test if threading works correctly"""
       shared_value = 0
       lock = threading.Lock()

       def worker():
           nonlocal shared_value
           for _ in range(1000):
               with lock:
                   shared_value += 1

       threads = [threading.Thread(target=worker) for _ in range(10)]
       for t in threads:
           t.start()
       for t in threads:
           t.join()

       return shared_value == 10000  # 10 threads * 1000 increments each

   if __name__ == "__main__":
       print(f"Free-threading enabled: {hasattr(sys, 'is_freethreaded') and sys.is_freethreaded}")

       # Test with ThreadPoolExecutor
       with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
           futures = [executor.submit(cpu_bound_task, 1000) for _ in range(8)]
           results = [f.result() for f in futures]
           print(f"ThreadPool test results: {len(results)} tasks completed")

       # Test thread safety
       if test_threading_safety():
           print("Thread safety test PASSED")
       else:
           print("Thread safety test FAILED")
   ```

2. **Check specific libraries**:
   ```python
   # Example for checking orjson
   try:
       import orjson
       # Test if orjson works in threaded context
       import threading
       import concurrent.futures

       def test_orjson():
           data = {"key": "value", "number": 42}
           serialized = orjson.dumps(data)
           deserialized = orjson.loads(serialized)
           return deserialized == data

       with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
           futures = [executor.submit(test_orjson) for _ in range(10)]
           results = [f.result() for f in futures]
           if all(results):
               print("orjson threading test PASSED")
           else:
               print("orjson threading test FAILED")
   except ImportError:
       print("orjson not available")
   ```

### Compatibility Resources

- **Python C API Documentation**: Look for `Py_GIL_DISABLED` macros and `PyUnstable_Thread*` APIs
- **PEP 703**: "Making the Global Interpreter Lock Optional in Python" (implemented in 3.14)
- **Library documentation**: Check individual library release notes for free-threading support
- **Community tracking**: Monitor discussions on python-dev mailing list and GitHub issues

## Best Practices

1. **Start small**: Enable free-threading for specific components before entire application
2. **Test thoroughly**: Run existing test suites with free-threading enabled
3. **Use stress testing**: Employ tools like `faulthandler` and timeout mechanisms
4. **Monitor performance**: Benchmark both single-threaded and multi-threaded scenarios
5. **Stay updated**: Keep dependencies updated to their latest free-threading compatible versions
6. **Document assumptions**: Clearly document which parts of your code assume free-threading behavior
7. **Consider fallback**: Implement graceful degradation to GIL mode when needed

## References

- PEP 703: Making the Global Interpreter Lock Optional in Python
- Python 3.14 Release Notes
- CPython source code: `Include/pythread.h` and `Python/pythread.c`
- "Python Multiprocessing vs Threading" performance comparison guides
