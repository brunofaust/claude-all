# Free-threading in Python 3.14 (PEP 703)

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

Consider free-threading mode when:
- You have CPU-bound Python workloads that could benefit from true parallelism
- Your application currently uses threading but is limited by the GIL
- You want to avoid the overhead of multiprocessing for shared-memory workloads
- Your dependencies are compatible with free-threading mode
- You're targeting Python 3.14+ as your minimum version

## Core Concepts

### What is Free-threading?

Free-threading (PEP 703) is an optional build mode in Python 3.14 that disables the Global Interpreter Lock (GIL), allowing multiple threads to execute Python bytecode simultaneously. This provides true parallelism for CPU-bound workloads traditionally limited by the GIL.

### Key Changes

1. **No GIL**: Threads can run in parallel on multiple CPU cores
2. **Reference counting becomes atomic**: Uses atomic operations instead of relying on the GIL for thread safety
3. **Garbage collection changes**: Requires updates to be thread-safe
4. **C extension compatibility**: Extensions need to be updated or run in compatibility mode

### Modes of Operation

Python 3.14 supports three modes:
- **Default mode**: GIL enabled (backward compatible)
- **Free-threading mode**: GIL disabled (requires opt-in)
- **Thread-safe mode**: GIL disabled but with additional safety checks (for extension development)

## Pros and Cons

### Pros

- **True parallelism**: CPU-bound threads can utilize multiple cores simultaneously
- **Lower overhead**: Compared to multiprocessing (no process startup/memory duplication)
- **Shared memory**: Threads share memory space naturally
- **Gradual adoption**: Can run existing code in compatibility mode
- **Better utilization**: Especially beneficial for I/O-bound + CPU-bound mixed workloads

### Cons

- **Extension compatibility**: Many C extensions need updates or run slower in compatibility mode
- **Debugging complexity**: Race conditions that were impossible with GIL may now occur
- **Memory overhead**: Atomic reference counting has slight performance cost
- **Limited adoption**: Early stage - ecosystem support is growing
- **Performance variance**: Some workloads may be slower due to atomic operations

## Implementation Approach

### Enabling Free-threading

To use free-threading, you need a Python 3.14 build with the `--disable-gil` flag:

```bash
# Building from source
./configure --disable-gil
make
make install

# Or using UV with free-threading Python
uv python install 3.14.0t  # t suffix indicates free-threading build
```

### In Your Application

1. **Detect free-threading mode** at runtime:

```python
import sys
import _thread

def is_freethreading():
    """Check if running in free-threading mode."""
    return hasattr(sys, 'getcount')  # Only available in free-threading builds

# Alternative check
def is_freethreading_alt():
    """Alternative check for free-threading mode."""
    return getattr(_thread, "getcount", None) is not None
```

2. **Update threading patterns**:

```python
import threading
from typing import Any

# Shared data structures need proper synchronization
counter = 0
counter_lock = threading.Lock()

def increment_counter():
    global counter
    with counter_lock:  # Still needed for compound operations
        counter += 1

# For atomic operations on simple types, consider using threading.Atomic
# (conceptual - actual implementation may vary)
```

3. **Consider using InterpreterPoolExecutor for CPU-bound work**:

```python
# For pure Python CPU-bound work that doesn't need shared state
from concurrent.futures import InterpreterPoolExecutor

def cpu_bound_task(n: int) -> int:
    """CPU-intensive computation."""
    return sum(i * i for i in range(n))

with InterpreterPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(cpu_bound_task, [1000, 2000, 3000, 4000]))
```

### Dependency Compatibility Checking

1. **Check for free-threading compatible versions**:

```python
import pkg_resources
import sys

def check_dependency_compatibility(package_name: str) -> bool:
    """Check if a package has free-threading support."""
    try:
        dist = pkg_resources.get_distribution(package_name)
        # Check if package has explicit free-threading support markers
        # This is heuristic-based since there's no standard metadata yet
        return True  # Placeholder - implement based on package documentation
    except pkg_resources.DistributionNotFound:
        return False

# Alternative: Check for known incompatible packages
KNOWN_INCOMPATIBLE = {
    'some-old-package': '2.0.0',  # Version where support was added
}

def is_compatible(package_name: str, version: str) -> bool:
    """Check if package version is compatible with free-threading."""
    if package_name in KNOWN_INCOMPATIBLE:
        min_version = KNOWN_INCOMPATIBLE[package_name]
        return pkg_resources.parse_version(version) >= pkg_resources.parse_version(min_version)
    return True  # Assume compatible unless known otherwise
```

2. **Runtime testing approach**:

```python
import threading
import time
from concurrent.futures import ThreadPoolExecutor

def test_freethreading_safety() -> bool:
    """Simple test to check if threading works correctly."""
    counter = 0
    lock = threading.Lock()

    def worker():
        nonlocal counter
        for _ in range(1000):
            with lock:
                counter += 1

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    return counter == 10 * 1000  # Should be 10000 if thread-safe

# Run this test during startup or in CI
if is_freethreading() and not test_freethreading_safety():
    raise RuntimeError("Free-threading mode detected but threading is not working correctly")
```

## Best Practices

### When to Choose Free-threading Over Alternatives

| Scenario | Recommended Approach |
|----------|---------------------|
| Pure Python CPU-bound work, no shared state | `InterpreterPoolExecutor` (Python 3.14+) |
| CPU-bound work with shared state, extensions compatible | Free-threading mode |
| CPU-bound C extensions (Polars, NumPy) | Traditional threading with `run_in_thread()` |
| Need process isolation | `ProcessPoolExecutor` |
| Mixed I/O and CPU-bound | Async with `run_in_thread()` for blocking parts |

### Code Adjustments

1. **Review shared state access**:
   - Operations that were atomic with GIL may now need locks
   - Review increments, appends to shared lists/dicts, etc.

2. **Consider using threading.Atomic** (when available):
   ```python
   # Conceptual - actual API may differ
   from threading import Atomic
   counter = Atomic(0)
   counter.increment()  # Atomic operation
   ```

3. **Update C extension usage**:
   - Check if extensions have free-threading support
   - Some may need to run in compatibility mode (slower but safe)
   - Others may require updates

### Migration Strategy

1. **Start with detection**: Add runtime checks for free-threading availability
2. **Test in compatibility mode**: Run existing test suite with free-threading Python
3. **Identify issues**: Look for race conditions, extension incompatibilities
4. **Fix incrementally**: Address threading safety issues one by one
5. **Enable fully**: Once stable, remove compatibility workarounds

## References

- [PEP 703 -- Making the Global Interpreter Lock Optional in CPython](https://peps.python.org/pep-0703/)
- [Python 3.14 Release Schedule](https://devguide.python.io/versions/3.14/)
- [Free-threading documentation](https://docs.python.org/3.14/c-api/init.html#free-threading-support)
- [Compatibility guide for extension authors](https://docs.python.org/3.14/c-api/freethreading.html)
