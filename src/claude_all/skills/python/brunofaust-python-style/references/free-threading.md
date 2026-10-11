# Free-threading (PEP 703) — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

- **Python 3.14+ only** — free-threading mode is available starting with Python 3.14
- **CPU-bound workloads** that can benefit from true parallelism without the GIL
- **When dependencies support free-threading** — check compatibility before enabling
- **For new projects** where you can control the entire dependency stack
- **When running in isolated environments** (containers, VMs) where you control the Python runtime

## Core Concepts

### What is Free-threading?

Free-threading is an optional build mode of CPython (Python 3.14+) that disables the Global Interpreter Lock (GIL), allowing multiple threads to execute Python bytecode concurrently. This provides true parallelism for CPU-bound Python code.

### Key Differences from Standard Python

| Aspect | Standard Python (with GIL) | Free-threading Python |
|--------|----------------------------|-----------------------|
| Thread execution | Only one thread executes Python bytecode at a time | Multiple threads can execute Python bytecode concurrently |
| CPU-bound threads | Limited by GIL, often slower due to context switching | Can utilize multiple CPU cores |
| I/O-bound threads | Benefit from concurrency (GIL released during I/O) | Similar benefit, with potential for better parallelism |
| Extension modules | Must be thread-safe or release GIL during blocking calls | Must be updated to work without GIL protection |
| Existing code | Most code works unchanged | May require updates for thread safety |

### Build Modes

Python 3.14 provides two interchangeable build modes:
1. **Default mode** (with GIL) - backward compatible
2. **Free-threading mode** (without GIL) - requires `--disable-gil` flag at compile time

Both modes can coexist on the same system; they are installed separately.

## Best Practices Summary

1. **Verify dependency compatibility** before enabling free-threading
2. **Use thread-safe data structures** or implement proper locking
3. **Prefer immutable data sharing** between threads when possible
4. **Test thoroughly** for race conditions that were hidden by the GIL
5. **Consider using `InterpreterPoolExecutor`** for CPU-bound work (alternative to free-threading)
6. **Monitor performance** - free-threading may increase memory usage and context switching overhead
7. **Use free-threading only when beneficial** - not all workloads see performance improvements

## Implementation

### Enabling Free-threading

To use free-threading, you must install or build Python 3.14+ with the `--disable-gil` flag:

```bash
# Building from source
./configure --disable-gil
make
make install

# Or using uv (if available)
uv python install 3.14.0 --disable-gil
```

### Checking if Running in Free-threading Mode

```python
import sys
import _thread

def is_freethreaded() -> bool:
    """Check if Python is running in free-threading mode."""
    return getattr(sys, '_is_gil_enabled', lambda: True)() == False

# Alternative check
def is_freethreaded_alt() -> bool:
    """Alternative method to check free-threading mode."""
    return hasattr(sys, 'getcount')  # Only available in free-threading builds

# Usage
if is_freethreaded():
    print("Running in free-threading mode")
else:
    print("Running in standard GIL mode")
```

### Writing Thread-safe Code

Without the GIL, explicit synchronization is required for shared mutable state:

```python
import threading
from typing import List

# Shared counter example - UNSAFE in free-threading
class Counter:
    def __init__(self):
        self.value = 0  # Not thread-safe!

    def increment(self):
        self.value += 1  # Race condition possible

# SAFE version with lock
class SafeCounter:
    def __init__(self):
        self._value = 0
        self._lock = threading.Lock()

    def increment(self):
        with self._lock:
            self._value += 1

    @property
    def value(self) -> int:
        with self._lock:
            return self._value
```

### Using Thread-local Storage

For state that doesn't need to be shared:

```python
import threading

# Thread-local storage (each thread gets its own instance)
local_data = threading.local()

def process_item(item):
    # Initialize thread-local data if needed
    if not hasattr(local_data, 'counter'):
        local_data.counter = 0
    local_data.counter += 1
    # Use local_data.counter safely within this thread
```

## Dependency Compatibility

### Checking Dependency Support

1. **Pure Python packages** - Generally work but may require thread-safety review
2. **C extension modules** - Must be updated to work without GIL:
   - Extensions must manage their own internal locking
   - Global state must be protected or made thread-local
   - Blocking operations should release the GIL (if still relevant) or be truly thread-safe

### Tools for Checking Compatibility

#### PyPI Trove Classifiers

Look for the ``Framework :: CPython :: 3.14`` classifier and specifically check for free-threading support indicators.

#### Manual Verification

1. Check documentation for mentions of Python 3.14 or free-threading support
2. Test in isolated environment with free-threading Python
3. Look for known issues in project trackers

#### Commonly Used Libraries Status (as of Python 3.14.0)

| Library | Free-threading Status | Notes |
|---------|----------------------|-------|
| NumPy | Experimental | Some operations thread-safe, others may require locks |
| pandas | Partial | Most operations work, but some internal operations may need review |
| requests | Compatible | HTTP library is thread-safe for concurrent use |
| SQLAlchemy | Compatible with pooling | Use connection pooling for thread safety |
| Redis-py | Compatible | Designed for concurrent use |
| Pillow | Variable | Some operations thread-safe, others may need serialization |
| cryptography | Compatible | Designed for concurrent use |

### Testing Dependency Compatibility

Create a test script to verify basic functionality:

```python
import concurrent.futures
import sys
import subprocess

def test_module_import(module_name: str) -> bool:
    """Test if a module can be imported and basic operations work."""
    try:
        module = __import__(module_name)
        # Perform a simple operation if applicable
        if module_name == 'numpy':
            import numpy as np
            arr = np.array([1, 2, 3])
            _ = arr.sum()
        elif module_name == 'requests':
            # Just test import - actual HTTP would require network
            pass
        return True
    except Exception as e:
        print(f"Failed to import/use {module_name}: {e}")
        return False

def concurrent_test(module_name: str, num_threads: int = 4) -> bool:
    """Test module under concurrent load."""
    def worker():
        return test_module_import(module_name)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker) for _ in range(num_threads)]
        results = [f.result() for f in futures]

    return all(results)

# Example usage
if __name__ == "__main__":
    modules_to_test = ['numpy', 'pandas', 'requests', 'sqlalchemy']

    for module in modules_to_test:
        print(f"Testing {module}...")
        if concurrent_test(module):
            print(f"  ✓ {module} appears compatible")
        else:
            print(f"  ✗ {module} may have issues")
```

### Migration Strategy

1. **Assess workload** - Determine if your application is CPU-bound and would benefit
2. **Check dependencies** - Verify critical dependencies support free-threading
3. **Test in isolation** - Run test suite with free-threading Python
4. **Gradual rollout** - Enable free-threading in non-critical services first
5. **Monitor performance** - Compare throughput and latency before/after enabling
6. **Address thread-safety issues** - Fix any race conditions that surface

## Pros and Cons

### Advantages

- **True parallelism** for CPU-bound Python threads
- **Better utilization** of multi-core systems
- **Reduced need** for process-based parallelism (multiprocessing) in some cases
- **Lower memory overhead** compared to multiprocessing (shared memory space)
- **Simpler sharing** of objects between threads (no pickling/unpickling)
- **Faster context switching** between threads vs processes

### Disadvantages

- **Increased memory usage** per thread (no GIL means more concurrent Python execution)
- **Potential for race conditions** in previously thread-unsafe code
- **Extension module compatibility** - many C extensions need updates
- **Debugging complexity** - race conditions can be non-deterministic
- **Performance variability** - some workloads may see degradation due to increased contention
- **Limited adoption** - ecosystem support is still evolving
- **No benefit** for I/O-bound workloads (similar to threaded GIL mode)

## When NOT to Use Free-threading

- **I/O-bound applications** - threading with GIL is sufficient
- **Applications with heavy shared mutable state** - high lock contention may negate benefits
- **Environments where you cannot control dependencies** - incompatible libraries will break
- **Security-sensitive applications** - increased attack surface for race condition exploits
- **Real-time systems** - unpredictable latency due to garbage collection and thread scheduling
- **When alternatives exist** - consider `InterpreterPoolExecutor`, `multiprocessing`, or async approaches

## References

- PEP 703 -- Making the Global Interpreter Lock Optional in CPython: https://peps.python.org/pep-0703/
- Python 3.14 What's New: https://docs.python.org/3.14/whatsnew/3.14.html
- Free-threading Python Wiki: https://wiki.python.org/moin/FreeThreading
- CPython Build Instructions: https://devguide.python.org/getting-started/setup-building/
