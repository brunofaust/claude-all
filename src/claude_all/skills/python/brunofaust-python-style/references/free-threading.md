# Free-threading (PEP 703) — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use Free-threading

Consider enabling free-threading mode in Python 3.14+ when:
- Your application is CPU-bound and can benefit from true parallelism across multiple cores
- You have workloads that are currently limited by the Global Interpreter Lock (GIL)
- You are using pure Python code or C extensions that are compatible with free-threading
- You want to avoid the overhead of multiprocessing while achieving parallelism
- Your deployment environment supports Python 3.14+ and you control the runtime

## Pros and Cons

### Pros
- **True parallelism**: Multiple threads can execute Python bytecode simultaneously without GIL contention
- **Lower overhead**: Compared to multiprocessing, free-threading avoids inter-process communication (IPC) costs
- **Shared memory**: Threads share the same memory space, making data sharing simpler than with processes
- **Compatibility**: Existing threaded code that worked with the GIL may see performance improvements without changes
- **Gradual adoption**: Can be enabled per-interpreter via environment variable or build flag

### Cons
- **Extension compatibility**: C extensions must be updated to be free-threading compatible; many popular libraries may not yet support it
- **Increased memory usage**: Each thread may require more memory due to lack of GIL protection for shared objects
- **Potential for new bugs**: Race conditions that were previously masked by the GIL may surface
- **Performance overhead**: The free-threading implementation may add overhead to single-threaded code
- **Limited availability**: Only available in Python 3.14+ (experimental in 3.13, official in 3.14)

## How to Implement

### Enabling Free-threading

There are two ways to enable free-threading in Python 3.14:

1. **Environment variable** (recommended for applications):
   ```bash
   PYTHONFREE=1 python3.14 your_script.py
   ```

2. **Build-time configuration** (for distributions):
   - Configure Python with `--enable-free-threading` flag
   - This builds a special Python interpreter that always runs in free-threading mode

### Writing Free-threading Compatible Code

When writing code for free-threading mode:

1. **Use threading primitives carefully**:
   - Traditional locks (`threading.Lock`, `threading.RLock`) still work but may have different performance characteristics
   - Consider using `threading.Mutex` (new in 3.14) which is optimized for free-threading
   - Avoid holding locks for long periods to reduce contention

2. **Handle shared state**:
   - Immutable data structures are safest for sharing between threads
   - For mutable state, use appropriate synchronization mechanisms
   - Consider using `queue.Queue` for thread-safe communication

3. **C extension considerations**:
   - If using C extensions, ensure they are built with free-threading support
   - Extensions must properly manage the GIL using the new PyThreadState APIs
   - Avoid extensions that rely on GIL for internal synchronization

### Example: Using Free-threading for CPU-bound Work

```python
import threading
import time
from concurrent.futures import ThreadPoolExecutor

def cpu_bound_work(n: int) -> int:
    """Example CPU-bound function."""
    total = 0
    for i in range(n):
        total += i * i
    return total

def parallel_computation(numbers: list[int]) -> list[int]:
    """Process numbers in parallel using free-threading."""
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(cpu_bound_work, n) for n in numbers]
        return [future.result() for future in futures]

if __name__ == "__main__":
    # Run with: PYTHONFREE=1 python3.14 this_script.py
    numbers = [1000000, 1000001, 1000002, 1000003]
    results = parallel_computation(numbers)
    print(f"Results: {results}")
```

## Checking Dependency Compatibility

Before enabling free-threading in production, verify that your dependencies are compatible:

### 1. Check Python Version
Ensure you are running Python 3.14 or later:
```python
import sys
assert sys.version_info >= (3, 14), "Free-threading requires Python 3.14+"
```

### 2. Check for Free-threading Support
Test if the interpreter was built with free-threading support:
```python
import sys
print(f"Free-threading supported: {sys.free_threading}")  # New in 3.14
```

### 3. Test Critical Dependencies
Create a compatibility test script:
```python
import sys
import threading
import time

def test_threading_basics():
    """Basic threading functionality test."""
    results = []
    lock = threading.Lock()

    def worker(item):
        time.sleep(0.01)  # Simulate work
        with lock:
            results.append(item * 2)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 10
    assert sorted(results) == [i * 2 for i in range(10)]
    print("✓ Basic threading works")

def test_gil_behavior():
    """Test that GIL behavior has changed (if free-threading enabled)."""
    if hasattr(sys, 'free_threading') and sys.free_threading:
        print("✓ Running in free-threading mode")
        # Add more specific tests here if needed
    else:
        print("ℹ Running with traditional GIL")

if __name__ == "__main__":
    test_threading_basics()
    test_gil_behavior()
```

### 4. Use Compatibility Checking Tools
- **pypi-free-threading**: A hypothetical tool that checks PyPI packages for free-threading compatibility markers
- **CI Integration**: Add free-threading tests to your continuous integration pipeline
- **Dependency Auditing**: Maintain a list of known incompatible packages in your project documentation

### 5. Common Incompatible Patterns to Watch For
- Extensions that use `PyGILState_Ensure()`/`PyGILState_Release()` incorrectly
- Manual GIL management using deprecated APIs
- Assumptions about atomicity of Python operations (e.g., `list.append` being thread-safe without GIL)
- C extensions with global state that isn't properly protected

## Recommendations for Adoption

1. **Start in Development**: Enable free-threading in your development environment first to identify issues
2. **Monitor Performance**: Benchmark your application with and without free-threading to ensure performance gains
3. **Gradual Rollout**: Enable free-threading for specific services or workloads before full adoption
4. **Fallback Strategy**: Maintain ability to run with traditional GIL for compatibility with unsupported dependencies
5. **Community Engagement**: Report compatibility issues to library maintainers and contribute fixes when possible

## Related References

- See `async-patterns.md` for traditional async/concurrency patterns that may still be relevant
- See `type-hints.md` for annotations that can help identify thread-unsafe patterns
- See `error-handling.md` for strategies to handle new types of race conditions that may emerge
