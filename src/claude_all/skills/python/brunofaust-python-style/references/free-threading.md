# Free-threading — Python 3.14's experimental no-GIL mode

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

- Building CPU-bound applications that can benefit from true parallelism
- Developing high-performance numerical computing or data processing pipelines
- Creating applications that need to utilize multiple CPU cores effectively
- Working with embarrassingly parallel problems (e.g., Monte Carlo simulations, image processing)
- When you have measured that the GIL is a bottleneck in your current Python 3.12/3.13 code
- For new projects where you can control the entire dependency stack
- When deploying to environments where you can ensure Python 3.14 free-threading support

## Pros and Cons

### Pros
- True parallel execution of Python threads without GIL contention
- Improved performance for CPU-bound workloads on multi-core systems
- Ability to use standard threading models for parallelism instead of multiprocessing
- Reduced complexity compared to managing separate processes
- Shared memory access between threads without serialization overhead
- Better utilization of modern multi-core hardware

### Cons
- Experimental feature in Python 3.14 (may have stability issues)
- Many popular libraries may not yet be thread-safe in free-threading mode
- Potential for race conditions in code that was previously GIL-protected
- Need to audit and potentially modify existing code for thread safety
- Limited tooling and debugging support compared to mature GIL mode
- Possible performance degradation for single-threaded or I/O-bound workloads
- Requires careful consideration of shared state and synchronization

## How to Implement

1. **Install Python 3.14 with free-threading support**:
   ```bash
   # Build Python 3.14 with --disable-gil flag
   ./configure --disable-gil --prefix=$HOME/python3.14-freethreaded
   make && make install
   ```

2. **Verify free-threading is enabled**:
   ```python
   import sys
   import _thread
   print(f"Free threading supported: {sys._is_gil_enabled() == False}")
   print(f"Thread API: {_thread}")
   ```

3. **Modify your code for thread safety**:
   - Identify shared mutable state
   - Use appropriate synchronization primitives (`threading.Lock`, `threading.RLock`, `threading.Semaphore`)
   - Consider using `threading.local()` for thread-local storage
   - Audit use of global variables and class attributes
   - Replace GIL-dependent patterns with explicit locks

4. **Update dependencies**:
   - Check if your dependencies support free-threading mode
   - Look for thread-safe versions or alternatives
   - Consider using pure Python libraries when possible
   - Test thoroughly with your specific dependency stack

5. **Example implementation pattern**:
   ```python
   import threading
   from concurrent.futures import ThreadPoolExecutor
   import queue

   # Thread-safe counter example
   class ThreadSafeCounter:
       def __init__(self):
           self._value = 0
           self._lock = threading.Lock()

       def increment(self):
           with self._lock:
               self._value += 1
               return self._value

       @property
       def value(self):
           with self._lock:
               return self._value

   # Usage in free-threaded environment
   def worker(counter, result_queue):
       for _ in range(1000):
           counter.increment()
       result_queue.put("done")

   def main():
       counter = ThreadSafeCounter()
       result_queue = queue.Queue()

       with ThreadPoolExecutor(max_workers=4) as executor:
           futures = [
               executor.submit(worker, counter, result_queue)
               for _ in range(4)
           ]
           # Wait for completion
           for future in futures:
               future.result()

       print(f"Final counter value: {counter.value}")

   if __name__ == "__main__":
       main()
   ```

## How to Check Dependencies

1. **Check Python version and free-threading support**:
   ```python
   import sys
   # Returns False when free-threading is enabled (GIL disabled)
   is_freethreaded = not sys._is_gil_enabled()
   print(f"Running in free-threading mode: {is_freethreaded}")
   ```

2. **Audit C extensions and native dependencies**:
   - Check if libraries use the Python C API correctly for free-threading
   - Look for modules that acquire the GIL manually (may need updates)
   - Verify that extensions use `Py_BEGIN_ALLOW_THREADS`/`Py_END_ALLOW_THREADS` properly
   - Check for use of deprecated C API functions that assume GIL

3. **Test for thread safety**:
   - Run your test suite with multiple threads
   - Use stress testing with high concurrency
   - Look for race conditions, deadlocks, or data corruption
   - Consider using tools like `threadsanitizer` or custom stress tests

4. **Check library documentation and compatibility**:
   - Look for explicit free-threading/Python 3.14 support statements
   - Check issue trackers for threading-related bugs
   - Test libraries in isolation with free-threading enabled
   - Consider maintaining compatibility layers for older Python versions

5. **Dependency verification script example**:
   ```python
   import subprocess
   import sys
   import pkg_resources

   def check_dependency_thread_safety(package_name):
       """Basic check if a package might have thread safety issues."""
       try:
           dist = pkg_resources.get_distribution(package_name)
           # This is a heuristic - real checking requires deeper inspection
           print(f"Checking {package_name} version {dist.version}")
           # Actual implementation would need to:
           # 1. Check for C extensions in the package
           # 2. Verify threading primitives usage
           # 3. Run specific thread safety tests
           return True  # Placeholder
       except pkg_resources.DistributionNotFound:
           print(f"Package {package_name} not found")
           return False

   # Example usage
   dependencies = ['numpy', 'pandas', 'requests', 'orjson']
   for dep in dependencies:
       check_dependency_thread_safety(dep)
   ```

6. **Monitoring and validation**:
   - Monitor for performance regressions
   - Watch for increased latency or throughput issues
   - Check for proper cleanup of threads and resources
   - Validate that existing tests still pass under free-threading
   - Consider gradual rollout with feature flags
