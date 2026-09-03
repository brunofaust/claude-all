# Free-threading in Python 3.14 — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

- **CPU-bound workloads** that can be parallelized across multiple cores (e.g., numerical computations, data processing, simulations).
- **Applications currently limited by the GIL** where multi-threading does not provide performance gains due to the GIL.
- **Scenarios where you control the dependencies** or can verify that your dependencies are free-threading compatible (or pure Python).
- **When using thread pools for concurrent execution** of CPU-bound tasks (as an alternative to multiprocessing with lower overhead).

**Do not use free-threading for:**
- I/O-bound workloads (asyncio or traditional threading with GIL is sufficient).
- Environments where you cannot control or verify dependency compatibility (many C extensions may not be thread-safe without the GIL).
- Situations requiring shared mutable state without explicit synchronization (free-threading removes the GIL's implicit protection).

## Pros and Cons

### Pros

- **True parallelism**: Multiple threads can execute Python bytecode simultaneously, utilizing multiple CPU cores.
- **Lower overhead than multiprocessing**: Avoids the cost of inter-process communication (IPC) and pickling for data sharing.
- **Shared memory space**: Threads share the same memory space, making it easier to share data between workers (with proper synchronization).
- **Compatibility with existing threading code**: Existing threading code can benefit without major rewrites (if dependencies are compatible).
- **Gradual adoption**: Can be enabled per-interpreter via environment variable or flag, allowing incremental testing.

### Cons

- **Extension compatibility risk**: Many C extensions rely on the GIL for thread safety and may crash or behave incorrectly without it.
- **Increased complexity for shared state**: Without the GIL, explicit locking (e.g., `threading.Lock`) is required for shared mutable state.
- **Debugging challenges**: Race conditions and subtle bugs may be harder to reproduce and diagnose.
- **Memory usage**: Each thread still has its own stack, and memory usage may increase with thread count.
- **Not a silver bullet**: Only benefits CPU-bound Python code; I/O-bound or already parallelized workloads may see little improvement.

## How to Implement

### Enabling Free-threading

Free-threading is enabled by setting the `PYTHON_GIL` environment variable to `0` or using the `-X gil=0` flag.

```bash
# Environment variable
PYTHON_GIL=0 python my_app.py

# Command-line flag
python -X gil=0 my_app.py
```

### Writing Free-threading Safe Code

1. **Avoid shared mutable state** where possible. Use immutable data or message passing (e.g., `queue.Queue`) between threads.
2. **Use explicit locks** when sharing mutable state is necessary:
   ```python
   import threading

   shared_counter = 0
   counter_lock = threading.Lock()

   def increment():
       global shared_counter
       with counter_lock:
           shared_counter += 1
   ```
3. **Prefer thread-local storage** for data that does not need to be shared:
   ```python
   import threading

   local_data = threading.local()

   def worker():
       local_data.value = compute_something()
       # Use local_data.value without locking
   ```
4. **Use concurrent.futures** with `ThreadPoolExecutor` for managing worker threads:
   ```python
   from concurrent.futures import ThreadPoolExecutor

   with ThreadPoolExecutor(max_workers=4) as executor:
       futures = [executor.submit(cpu_bound_task, arg) for arg in arguments]
       results = [f.result() for f in futures]
   ```

### Checking Dependency Compatibility

1. **Check for explicit free-threading support**:
   - Look for documentation or release notes mentioning Python 3.14 or free-threading/GIL-disabled mode.
   - Check if the package provides wheels tagged with `abi3` or indicates thread-safety.
2. **Test in isolation**:
   - Run your application's unit tests with `PYTHON_GIL=0` to detect crashes or incorrect behavior.
   - Focus on tests that exercise the dependency's core functionality.
3. **Use the `sys` module to check GIL status** at runtime:
   ```python
   import sys

   def is_gil_disabled():
       # In Python 3.14+, _is_gil_enabled() returns False when GIL is disabled
       return not sys._is_gil_enabled()  # Note: private API, use with caution

   if is_gil_disabled():
       # Apply free-threading specific logic
       pass
   ```
4. **Consult the Python C API documentation** for extension maintainers:
   - Extensions must use the new `PyMutex` API or ensure internal thread-safety when the GIL is disabled.
   - Refer to [PEP 703](https://peps.python.org/pep-0703/) for details on making extensions free-threading compatible.
5. **Monitor for known issues**:
   - Check the issue trackers of your dependencies for reports related to free-threading or GIL-disabled mode.
   - Popular libraries like NumPy, pandas, and others may have ongoing work; verify their status.

## Example: Free-threading Enabled Service

Here's an example of a CPU-intensive service that benefits from free-threading:

```python
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List

def is_prime(n: int) -> bool:
    """CPU-intensive primality test."""
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    limit = int(math.isqrt(n)) + 1
    for i in range(3, limit, 2):
        if n % i == 0:
            return False
    return True

def count_primes_in_range(start: int, end: int) -> int:
    """Count primes in a given range (inclusive)."""
    return sum(1 for n in range(start, end + 1) if is_prime(n))

def main() -> None:
    # Example: Count primes in 10 ranges of 100,000 numbers each
    ranges = [(i * 100_000, (i + 1) * 100_000 - 1) for i in range(10)]

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(count_primes_in_range, start, end)
            for start, end in ranges
        ]
        results = [f.result() for f in futures]

    total_primes = sum(results)
    print(f"Total primes found: {total_primes}")

if __name__ == "__main__":
    # Note: Run with PYTHON_GIL=0 or -X gil=0 to enable free-threading
    main()
```

**To run with free-threading:**
```bash
PYTHON_GIL=0 python prime_counter.py
# or
python -X gil=0 prime_counter.py
```

## Further Reading

- [PEP 703 – Making the Global Interpreter Lock Optional in CPython](https://peps.python.org/pep-0703/)
- [Python 3.14 Release Schedule](https://devguide.python.org/versions/3.14/)
- [Threads Without the GIL: A Practical Guide](https://blog.ianswett.dev/pthreads-without-the-gil) (example external resource)
