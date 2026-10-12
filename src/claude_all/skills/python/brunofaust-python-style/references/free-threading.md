# Free-threading (PEP 703) — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Understanding Free-threading in Python 3.14

Python 3.14 introduces an optional free-threading mode (PEP 703) that disables the Global Interpreter Lock (GIL), allowing true parallelism in multi-threaded Python programs. This feature is opt-in via a special build of Python and requires careful consideration for adoption.

## When to Use Free-threading

Consider enabling free-threading when:

- Your application is **CPU-bound** and currently limited by the GIL
- You have **significant parallelizable workloads** that can utilize multiple cores
- You're using **pure Python or extensions that release the GIL** (like NumPy, Pandas)
- You have **tested thoroughly** for thread-safety in your codebase and dependencies
- You're deploying in a **controlled environment** where you manage the Python runtime

Avoid free-threading when:

- Your application is **I/O-bound** (network, disk) where asyncio already excels
- You rely heavily on **C extensions** that may not be thread-safe without the GIL
- You need **maximum compatibility** with existing Python packages
- Your code uses **thread-unsafe patterns** that were previously protected by the GIL

## Pros and Cons

### Advantages

- **True parallelism**: Multiple Python threads can execute Python bytecode simultaneously
- **Better utilization of multi-core systems** for CPU-bound workloads
- **Lower overhead** than multiprocessing for shared-memory workloads
- **Compatibility with existing threading code** (no need to rewrite to multiprocessing)
- **Gradual adoption** possible — can run existing code with free-threading build

### Disadvantages

- **Increased memory overhead** due to finer-grained locking requirements
- **Potential performance regression** in single-threaded scenarios
- **Thread-safety bugs** that were masked by the GIL may surface
- **Limited package compatibility** — many extensions need updates for free-threading
- **Debugging complexity** — race conditions are harder to reproduce and diagnose
- **Requires special Python build** — not available in standard distributions initially

## Implementation Guide

### Building Python with Free-threading

To use free-threading, you need a special build of Python 3.14:

```bash
# Option 1: Build from source
./configure --enable-free-threading
make -j$(nproc)
sudo make install

# Option 2: Use a distribution that provides free-threading builds
# (Check with your package manager or Python distributor)
```

### Verifying Free-threading Mode

Check if free-threading is enabled at runtime:

```python
import sys
import _thread

def is_freethreading_enabled():
    """Check if Python is running in free-threading mode."""
    return hasattr(sys, "getfreethreadcount") and sys.getfreethreadcount() > 0

# Alternative check
import _thread
if _thread.getfreethreadcount():
    print("Running in free-threading mode")
else:
    print("Running with GIL enabled")
```

### Writing Thread-safe Code

With free-threading, traditional GIL-protected operations now require explicit synchronization:

```python
# UNSAFE in free-threading mode without protection
counter = 0

def increment_unsafe():
    global counter
    counter += 1  # Race condition possible

# SAFE with threading.Lock
import threading

counter = 0
counter_lock = threading.Lock()

def increment_safe():
    global counter
    with counter_lock:
        counter += 1

# Or use threading.RLock for reentrant locks
# Or use queue.Queue for producer-consumer patterns
```

### Using concurrent.futures with Free-threading

The `ThreadPoolExecutor` now provides true parallelism:

```python
from concurrent.futures import ThreadPoolExecutor
import math

def is_prime(n):
    if n < 2:
        return False
    for i in range(2, int(math.isqrt(n)) + 1):
        if n % i == 0:
            return False
    return True

# With free-threading, this utilizes multiple cores
with ThreadPoolExecutor(max_workers=4) as executor:
    numbers = range(1000000, 1001000)
    results = list(executor.map(is_prime, numbers))
```

## Dependency Compatibility Checking

### Checking Extension Modules

Extensions must be updated to work with free-threading. Check compatibility:

```python
import sys
import threading

def check_extension_thread_safety(module_name):
    """Basic check if an extension module claims free-threading support."""
    try:
        module = __import__(module_name)
        # Look for free-threading related attributes
        if hasattr(module, '__freethreading__'):
            return module.__freethreading__
        # Some modules may expose this differently
        return getattr(module, '_is_freethreading_safe', True)
    except ImportError:
        return False

# Example usage
if check_extension_thread_safety('numpy'):
    print("NumPy claims free-threading compatibility")
else:
    print("NumPy may not be free-threading safe")
```

### Using PyPI Metadata

Look for these indicators in package metadata:
- **Trojan Classifier**: `Framework :: FreeThreading`
- **Package Documentation**: Explicit free-threading support statements
- **Version Requirements**: Minimum versions that support free-threading (often 3.14+)

### Testing Strategy

1. **Run your test suite** with free-threading enabled
2. **Focus on race condition detection** using tools like:
   - `threading` module locks and debugging
   - `faulthandler` for crash diagnostics
   - Stress testing with high thread counts
3. **Use dependency checkers** like `pip check` or `pipdeptree` to identify incompatible packages
4. **Monitor performance** — some workloads may slow down due to increased locking overhead

## Best Practices for Adoption

### Gradual Migration Path

1. **Start with profiling** to identify CPU-bound bottlenecks
2. **Test critical paths** with free-threading in a staging environment
3. **Use feature flags** to enable free-threading only for specific workloads
4. **Implement monitoring** for thread-safety issues in production
5. **Have a rollback plan** to disable free-threading if issues arise

### Code Patterns to Avoid

- **Global mutable state** without proper locking
- **Assuming atomicity** of operations like `list.append()` or `dict.update()`
- **Relying on GIL for implicit synchronization**
- **Thread-local storage** that leaks between threads (less relevant but still important)

### Recommended Patterns

- **Use immutable data structures** where possible
- **Prefer queue.Queue** for thread communication
- **Use threading.Lock/RLock** for shared mutable state
- **Leverage concurrent.futures** for parallel execution patterns
- **Consider asyncio for I/O-bound work** even with free-threading available

## When Free-threading Isn't the Answer

Remember that free-threading addresses CPU-bound Python limitations. For many applications:

- **Asyncio remains superior** for I/O-bound concurrent work (web servers, APIs)
- **Multiprocessing** is still better for CPU-work requiring strong isolation
- **C extensions/Numpy** often already release the GIL for parallelism
- **Free-threading adds complexity** — only adopt when profiling shows a clear bottleneck solvable by parallel Python execution

## References

- PEP 703: Making the Global Interpreter Lock Optional in CPython
- Python 3.14 What's New: Free-threading section
- PyPI FreeThreading Trojan Classifier: https://pypi.org/classifiers/
- "Python without the GIL" — official documentation and tutorials
