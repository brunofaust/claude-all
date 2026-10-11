# Free-threading (PEP 703) — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

Consider free-threading builds of Python 3.14+ when:

- You have CPU-bound Python code that is currently limited by the Global Interpreter Lock (GIL)
- Your workload consists of multiple threads that can run in parallel on multi-core systems
- You are using pure Python code or C extensions that are already GIL-free or have been updated for free-threading
- You want to avoid the overhead of processes (inter-process communication, pickling) while achieving parallelism
- Your application is I/O-bound but has occasional CPU-bound spikes that could benefit from true parallelism

## Pros and Cons

### Pros

- **True parallelism**: Multiple threads can execute Python bytecode simultaneously without GIL contention
- **Lower overhead than processes**: No need for inter-process communication (IPC) or pickling/unpickling data
- **Shared memory**: Threads share the same memory space, making it easier to share data between workers
- **Compatibility**: Existing threading code continues to work; no changes required for thread-safe code
- **Gradual adoption**: Can be adopted incrementally as dependencies become compatible

### Cons

- **Memory overhead**: Each thread requires its own memory for objects (no more implicit sharing via GIL)
- **Increased locking pressure**: Data structures that were previously safe due to GIL may now require explicit locking
- **C extension compatibility**: Many C extensions need updates to be free-threading safe
- **Debugging complexity**: Race conditions and deadlocks become more likely and harder to debug
- **Performance variability**: Some workloads may see slower performance due to increased locking overhead or cache effects

## How to Implement

### Checking for Free-threading Support

First, verify you are running a free-threading build:

```python
import sys
import _thread

def is_freethreading():
    """Check if running in a free-threading Python build."""
    return hasattr(sys, "getfreethreadcount") and sys.getfreethreadcount() > 1

# Alternative check
def is_freethreading_alt():
    """Check if running in a free-threading Python build."""
    return "_thread" in sys.modules and hasattr(_thread, "getfreethreadcount")
```

### Basic Usage

Free-threading works with standard threading primitives:

```python
import threading
import time

def worker(num):
    """CPU-bound worker function."""
    result = 0
    for i in range(10_000_000):
        result += i * i
    print(f"Worker {num} finished with result {result}")

# Create and start threads
threads = []
for i in range(4):
    t = threading.Thread(target=worker, args=(i,))
    threads.append(t)
    t.start()

# Wait for completion
for t in threads:
    t.join()
```

### Using ThreadPoolExecutor

The standard `concurrent.futures.ThreadPoolExecutor` works unchanged:

```python
from concurrent.futures import ThreadPoolExecutor
import math

def is_prime(n):
    """CPU-bound prime check."""
    if n < 2:
        return False
    for i in range(2, int(math.isqrt(n)) + 1):
        if n % i == 0:
            return False
    return True

def check_primes(numbers):
    """Check primality for a list of numbers."""
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(is_prime, numbers))
    return results

# Usage
numbers = [10**9 + 7, 10**9 + 9, 10**9 + 21, 10**9 + 33]
print(check_primes(numbers))  # [True, True, False, True]
```

### Important Considerations

1. **Thread Safety**: Data structures accessed by multiple threads must be protected with locks:
   ```python
   import threading
   
   class Counter:
       def __init__(self):
           self._value = 0
           self._lock = threading.Lock()
       
       def increment(self):
           with self._lock:
               self._value += 1
       
       @property
       def value(self):
           with self._lock:
               return self._value
   ```

2. **Avoiding Global State**: Minimize shared mutable state between threads when possible.

3. **Using Queues for Communication**: Use `queue.Queue` for thread-safe communication:
   ```python
   import threading
   import queue
   
   def worker(q, result_q):
       while True:
           item = q.get()
           if item is None:
               break
           # Process item
           result_q.put(process(item))
           q.task_done()
   
   q = queue.Queue()
   result_q = queue.Queue()
   # Start workers, feed queue, collect results
   ```

## Checking Dependency Compatibility

### 1. Check Python Build

Verify you're running a free-threading build:

```python
import sys
print(f"Python {sys.version}")
print(f"Free-threading support: {'yes' if hasattr(sys, 'getfreethreadcount') else 'no'}")
if hasattr(sys, 'getfreethreadcount'):
    print(f"Free thread count: {sys.getfreethreadcount()}")
```

### 2. Check Key Dependencies

Some popular libraries and their free-threading status (as of Python 3.14 release):

- **Native Python packages** (pure Python): Generally work without changes
- **C extensions**: Need to be checked individually
  - NumPy: Typically releases GIL during computation, should benefit
  - Pandas: Depends on NumPy; check for GIL-releasing operations
  - PyTorch/TensorFlow: Have their own parallelism; may not need free-threading
  - lxml: May require updates for free-threading safety
  - Pillow: Some operations release GIL; check documentation

### 3. Testing for Compatibility

Run your test suite with increased thread count to detect race conditions:

```bash
# Run with multiple threads to increase chance of detecting race conditions
PYTHONTHREADDEBUG=1 python -m pytest tests/ -n auto
```

### 4. Using `python -m perf` to Check for Regression

Benchmark critical paths to ensure free-threading doesn't introduce overhead:

```bash
python -m perf script benchmarks.json
```

### 5. Dependency Validation Tools

- **`pip check`**: Verify dependency consistency
- **`cytracer`**: Trace C extension calls to see GIL behavior
- **Custom scripts**: Check for known incompatible packages

### 6. Community Resources

- Python 3.14 free-threading wiki: https://wiki.python.org/moin/FreeThreading
- PEP 703 -- Making the Global Interpreter Lock Optional in CPython
- Manylinux 2014+ wheels tagged with `freethreaded` compatibility indicator

## Best Practices for Free-threading

1. **Start with profiling**: Identify if your bottleneck is truly CPU-bound and GIL-limited
2. **Use appropriate granularity**: Too fine-grained threading increases locking overhead
3. **Prefer existing parallelism libraries**: Consider `concurrent.futures`, `joblib`, or `ray` for complex patterns
4. **Test extensively**: Free-threading exposes race conditions that were hidden by the GIL
5. **Monitor memory usage**: Each thread has its own memory footprint
6. **Consider hybrid approaches**: Use free-threading for CPU-bound parts and asyncio for I/O-bound parts
7. **Document assumptions**: Clearly mark which parts of your code are thread-safe in free-threading builds
8. **Update dependencies**: Encourage maintainers of your dependencies to provide free-threading compatible wheels

## When Not to Use

Avoid free-threading when:

- Your workload is primarily I/O-bound (asyncio is more appropriate)
- You have complex shared state that would require extensive locking
- Your dependencies are not yet compatible and cannot be updated
- You're developing libraries that need to support both threaded and free-threading builds
- Simple performance testing shows no benefit or degradation for your specific workload

## Example: Numerical Integration

Here's an example showing the benefit of free-threading for a CPU-bound numerical task:

```python
import threading
import math
from concurrent.futures import ThreadPoolExecutor

def integrate_segment(f, a, b, n_samples):
    """Integrate function f from a to b using midpoint rule."""
    dx = (b - a) / n_samples
    total = 0.0
    for i in range(n_samples):
        x = a + (i + 0.5) * dx
        total += f(x) * dx
    return total

def parallel_integrate(f, a, b, n_samples, n_workers=4):
    """Integrate f from a to b using multiple workers."""
    segment_width = (b - a) / n_workers
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = []
        for i in range(n_workers):
            seg_a = a + i * segment_width
            seg_b = seg_a + segment_width
            future = executor.submit(integrate_segment, f, seg_a, seg_b, n_samples // n_workers)
            futures.append(future)
        return sum(future.result() for future in futures)

# Example usage: integrate sin(x) from 0 to pi
if __name__ == "__main__":
    result = parallel_integrate(math.sin, 0, math.pi, 10_000_000)
    print(f"Integral of sin(x) from 0 to pi: {result}")  # Should be close to 2.0
```

This example shows how free-threading can provide true parallelism for CPU-bound numerical work that was previously limited by the GIL.