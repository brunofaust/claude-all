# Free-threading in Python 3.14 — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Free-threading (PEP 703) in Python 3.14

Python 3.14 introduces an optional free-threading mode (build with `--disable-gil`) that removes the Global Interpreter Lock (GIL), allowing true parallelism in Python threads.

## When to Use

- **CPU-bound workloads** that can benefit from true parallelism (not just I/O-bound tasks)
- **Applications currently using multiprocessing** to bypass GIL limitations
- **Workloads with fine-grained parallelism** where process creation overhead is too high
- **Libraries and frameworks** that want to leverage multiple cores without changing their threading model
- **Scientific computing, data processing, and simulations** that are CPU-intensive

### Not Recommended For

- **I/O-bound applications** (asyncio or threading already work well)
- **Applications with heavy reliance on C extensions** that may not be thread-safe
- **Simple scripts** where the overhead outweighs benefits
- **Code with shared mutable state** without proper synchronization

## Pros and Cons

### Pros

- **True parallelism**: Multiple Python threads can run simultaneously on multiple cores
- **Lower overhead**: Compared to multiprocessing (no pickle/unpickle, shared memory)
- **Compatibility**: Existing threaded code may see performance improvements without changes
- **Gradual adoption**: Can be enabled per-interpreter, not requiring full code rewrite
- **Shared memory**: Threads share memory space naturally (vs. process isolation)

### Cons

- **Extension compatibility**: C extensions must be thread-safe and may require updates
- **Increased memory usage**: Per-object reference counting overhead increases
- **Potential slowdown**: Single-threaded performance may decrease slightly due to atomic refcounting
- **New concurrency bugs**: Race conditions that were hidden by GIL may surface
- **Limited adoption**: Early stage; not all libraries support it yet
- **Build requirement**: Requires building Python with `--disable-gil` flag

## How to Implement

### Building Python 3.14 with Free-threading

```bash
# Download and build Python 3.14 with free-threading enabled
wget https://www.python.org/ftp/python/3.14.0/Python-3.14.0.tgz
tar -xzf Python-3.14.0.tgz
cd Python-3.14.0
./configure --disable-gil --enable-optimizations
make -j$(nproc)
sudo make altinstall  # installs as python3.14
```

### Checking if Free-threading is Enabled

```python
import sys
import _thread

def is_freethreading_enabled():
    """Check if Python is running in free-threading mode."""
    return hasattr(sys, 'getcount')  # Only available in free-threading builds

# Alternative check
import sysconfig
def is_freethreading_build():
    return sysconfig.get_config_var('PYTHON_GIL') == '0'

# Runtime check
import _thread
def is_gil_disabled():
    # In free-threading mode, locks behave differently
    lock = _thread.allocate_lock()
    # Attempt to acquire from multiple threads - if GIL is disabled, this tests true threading
    return True  # Simplified - actual check requires more sophisticated testing
```

### Writing Free-threading Compatible Code

```python
import threading
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar, List

T = TypeVar('T')

def parallel_map(func: Callable[[int], T], items: List[int]) -> List[T]:
    """
    Map function over items using thread pool.
    In free-threading mode, this achieves true parallelism for CPU-bound func.
    """
    # Check if we're in free-threading mode to adjust behavior
    use_freethreading = hasattr(sys, 'getcount')

    # In free-threading, we can use more aggressive threading for CPU work
    max_workers = min(32, (len(items) + 1) // 2) if use_freethreading else min(10, len(items))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(func, item) for item in items]
        return [future.result() for future in futures]
```

### Synchronization Primitives

Free-threading makes proper synchronization more critical:

```python
import threading
from threading import Lock, RLock, Semaphore, Barrier
from typing import Shared  # Hypothetical - actual sharing mechanisms may vary

# Shared counters need protection
counter = 0
counter_lock = Lock()

def increment_counter():
    global counter
    with counter_lock:
        # In free-threading, this lock is actually necessary
        current = counter
        # Simulate some work
        current += 1
        counter = current

# For better performance in free-threading, consider:
# - Using atomic operations where possible (via ctypes or specialized modules)
# - Minimizing lock scope
# - Using threading.local() for per-thread state when appropriate
```

## Checking Dependency Compatibility

### 1. Check Python Extension Compatibility

```python
import sys
import importlib.util

def check_extension_thread_safety(module_name: str) -> bool:
    """
    Basic check for whether an extension might be thread-safe.
    This is heuristic - actual safety depends on implementation.
    """
    try:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            return False

        # Check if it's a built-in extension
        if spec.origin == "built-in":
            # Built-ins like math, json are generally safe
            safe_builtins = {'math', 'json', 'datetime', 'collections', 'itertools', 'heapq', 'bisect'}
            return module_name.split('.')[0] in safe_builtins

        # For other extensions, we can't easily determine - assume may need checking
        return False  # Conservative approach - assume not safe until proven
    except Exception:
        return False

# Usage
extensions_to_check = ['numpy', 'pandas', 'lxml', 'cryptography']
for ext in extensions_to_check:
    if check_extension_thread_safety(ext):
        print(f"{ext}: Likely thread-safe")
    else:
        print(f"{ext}: May require verification for free-threading")
```

### 2. Use Tools to Detect Potential Issues

- **Compile with `-Werror=thread-safety`** (if supported by compiler)
- **Run existing test suite** with free-threading Python
- **Use stress testing** with multiple threads
- **Check for global state** in C extensions
- **Verify reference counting** is atomic in custom extensions

### 3. Dependency Verification Checklist

For each dependency:
- [ ] Check if library provides free-threading wheels or documentation
- [ ] Look for `--disable-gil` support in build instructions
- [ ] Test with free-threading Python in isolated environment
- [ ] Verify no crashes or deadlocks under concurrent load
- [ ] Ensure performance scales with core count (not hindered by GIL)
- [ ] Check for updated versions that mention free-threading support

## Interaction with Skill Rules

### Impact on Existing Patterns

1. **`run_in_thread()`**:
   - Still valid for I/O-bound work and C extensions that release GIL
   - For pure Python CPU work, free-threading may provide better performance
   - Consider detecting free-threading mode to adjust worker counts

2. **ThreadPoolExecutor vs ProcessPoolExecutor**:
   - In free-threading mode, ThreadPoolExecutor may be preferred for CPU work
   - ProcessPoolExecutor still useful for isolation and when extensions aren't thread-safe

3. **Asyncio Integration**:
   - Asyncio event loop remains single-threaded per loop
   - Free-threading doesn't change asyncio fundamentals
   - Can run multiple event loops in parallel threads (True parallelism for asyncio)

4. **Semaphore and Lock Usage**:
   - More critical than ever - race conditions that were GIL-protected now exposed
   - Skill's existing semaphore patterns remain valid and important

### Recommendations for Skill Users

- **Continue using `run_in_thread()`** for blocking I/O and C extensions
- **Consider free-threading detection** for CPU-bound pure Python workloads
- **Update thread pool sizes** based on detected free-threading mode
- **Audit custom C extensions** for thread safety before enabling free-threading
- **Monitor performance** - single-threaded speed may slightly decrease
- **Use free-threading for new CPU-intensive services** where appropriate

## Migration Strategy

### Phase 1: Assessment
1. Profile application to identify CPU-bound sections
2. Inventory dependencies and check free-threading compatibility
3. Run test suite with free-threading Python (in CI if possible)

### Phase 2: Preparation
1. Fix any thread-safety issues in internal code
2. Update dependencies to free-threading-compatible versions
3. Add free-threading detection capabilities to codebase
4. Benchmark performance with and without free-threading

### Phase 3: Deployment
1. Deploy free-threading Python in staging environment
2. Monitor for correctness and performance
3. Gradually roll out to production
4. Adjust thread pool sizes and concurrency limits based on observations

## References

### Official Documentation
- [PEP 703 – Making the Global Interpreter Lock Optional in CPython](https://peps.python.org/pep-0703/)
- [Python 3.14 Release Schedule](https://devguide.python.io/versions/3.14/)
- [What’s New in Python 3.14](https://docs.python.org/3.14/whatsnew/3.14.html)

### Community Resources
- [Free-threading Wiki](https://wiki.python.org/moin/FreeThreading)
- [Discuss: Free-threading Python](https://discuss.python.org/c/core-dev/12)
- [GitHub: free-threading-benchmarks](https://github.com/python/cpython/tree/main/Tools/free_threading)

### Tools and Libraries
- [`fypp`](https://github.com/inducer/fypp) - For preprocessing free-threading compatible C extensions
- [`nogil`](https://github.com/colesbury/nogil) - Experimental free-threading branches
- [`perf`](https://github.com/python/perf) - Performance testing suite

### Related Skill References
- [async-patterns.md](async-patterns.md) - For contrast with asyncio approach
- [caching.md](caching.md) - Considerations for shared caches in free-threading
- [project-structure.md](project-structure.md) - Impact on service design
