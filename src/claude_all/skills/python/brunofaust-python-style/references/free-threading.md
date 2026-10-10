# Free-threading (PEP 703) — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Free-threading Mode in Python 3.14

Python 3.14 introduces an experimental build mode that makes the Global Interpreter Lock (GIL) optional, enabling true parallelism in multi-threaded Python programs. This feature is accessed by building CPython with the `--disable-gil` flag.

## When to Use Free-threading

- **CPU-bound workloads** that can be parallelized across multiple cores
- **Applications currently limited by the GIL** in multi-threaded scenarios
- **New projects** where you can control the entire dependency stack
- **Migration path**: Start with free-threading mode in development/testing before production deployment

**Not recommended for**:
- Applications relying heavily on C extensions that aren't free-threading compatible
- Projects requiring maximum compatibility with existing Python packages
- I/O-bound workloads (asyncio remains superior for these)

## Core Concepts

### How Free-threading Works

In traditional CPython, the GIL ensures only one thread executes Python bytecode at a time. Free-threading mode removes this lock, allowing multiple threads to execute Python code simultaneously on different CPU cores.

### Thread Safety Implications

Without the GIL:
- Python's built-in data structures (list, dict, set) remain thread-safe for single operations
- Compound operations (check-then-act) require explicit synchronization
- Extension modules must manage their own internal state protection
- The `threading.Lock` and related primitives work as expected for synchronization

### Checking Free-threading Support

```python
import sys

# Check if running in free-threading mode
is_freethreaded = sys.config.get('free_threading', False)

# Alternative: check for the _thread module's GIL status
import _thread
print(f"GIL enabled: {_thread.get_gil_enabled()}")
```

## Implementation Guidelines

### Writing Free-threading Compatible Code

#### 1. Use Proper Synchronization
```python
import threading
from collections import defaultdict

# Shared state protected by locks
counter = 0
counter_lock = threading.Lock()

def increment_counter():
    global counter
    with counter_lock:
        counter += 1

# Thread-safe dictionary updates
shared_dict = defaultdict(int)
dict_lock = threading.Lock()

def update_dict(key):
    with dict_lock:
        shared_dict[key] += 1
```

#### 2. Prefer Queue for Producer-Consumer Patterns
```python
import threading
import queue

def worker(q: queue.Queue, results: list):
    while True:
        item = q.get()
        if item is None:  # Sentinel to stop
            break
        # Process item
        result = process_item(item)
        with results_lock:
            results.append(result)
        q.task_done()

# Usage
q = queue.Queue()
results = []
results_lock = threading.Lock()
threads = []
for _ in range(num_workers):
    t = threading.Thread(target=worker, args=(q, results))
    t.start()
    threads.append(t)
```

#### 3. Use Concurrent.futures with ThreadPoolExecutor
```python
from concurrent.futures import ThreadPoolExecutor
import threading

# Thread-local storage for per-thread state
thread_local = threading.local()

def init_worker():
    # Initialize per-worker resources
    thread_local.resource = create_expensive_resource()

def process_item(item):
    # Access thread-local state
    resource = thread_local.resource
    return process_with_resource(item, resource)

with ThreadPoolExecutor(
    max_workers=num_workers,
    initializer=init_worker
) as executor:
    futures = [executor.submit(process_item, item) for item in items]
    results = [f.result() for f in futures]
```

### Extension Module Considerations

If using or creating C extensions:
1. Ensure extensions are compiled with free-threading support
2. Audit global state for thread safety
3. Use Python's threading primitives or implement proper locking
4. Test thoroughly under free-threading mode

## Pros and Cons

### Advantages
| Benefit | Description |
|---------|-------------|
| True parallelism | Multiple threads can execute Python code simultaneously |
| Better CPU utilization | Utilizes all cores for CPU-bound Python workloads |
| Lower overhead than processes | Threads share memory space, avoiding IPC costs |
| Compatibility with existing threading code | Most threaded code works without changes |
| Gradual adoption | Can enable per-interpreter or per-module |

### Disadvantages
| Drawback | Description |
|----------|-------------|
| Extension compatibility | C extensions must be audited for thread safety |
| Potential performance regression | Single-threaded speed may slightly decrease |
| Increased complexity | Need to consider thread safety more carefully |
| Debugging challenges | Race conditions may emerge that were hidden by GIL |
| Experimental status | Feature is new and may have edge cases |

## Dependency Compatibility Checking

### 1. Check Interpreter Build
```python
import sys
import platform

def is_freethreaded_build():
    """Check if Python was built with free-threading support."""
    return hasattr(sys, 'config') and sys.config.get('free_threading', False)

def get_implementation_details():
    """Get detailed implementation information."""
    return {
        'implementation': platform.python_implementation(),
        'version': platform.python_version(),
        'freethreaded': is_freethreaded_build(),
        'gil_enabled': _thread.get_gil_enabled() if hasattr(_thread, 'get_gil_enabled') else True
    }
```

### 2. Audit Dependencies
```python
import pkg_resources
import sys

def check_dependency_compatibility(package_names=None):
    """
    Check if installed packages are free-threading compatible.
    Returns tuple: (compatible_packages, incompatible_packages, unknown_packages)
    """
    if package_names is None:
        package_names = [proj.key for proj in pkg_resources.working_set]

    compatible = []
    incompatible = []
    unknown = []

    # Known incompatible packages (examples - adjust based on current knowledge)
    known_incompatible = {
        'numpy': '<1.26.0',  # Example version
        'pandas': '<2.1.0',
        # Add more as compatibility data becomes available
    }

    for pkg_name in package_names:
        try:
            pkg = pkg_resources.get_distribution(pkg_name)
            # Check against known compatibility database
            if pkg_name in known_incompatible:
                # Version check would go here
                incompatible.append((pkg_name, pkg.version))
            else:
                # Assume compatible unless known otherwise
                compatible.append((pkg_name, pkg.version))
        except pkg_resources.DistributionNotFound:
            unknown.append(pkg_name)

    return compatible, incompatible, unknown
```

### 3. Runtime Testing Approach
```python
import threading
import time
import sys

def test_freethreading_safety():
    """Simple test to check if basic threading works without GIL issues."""
    if not hasattr(sys, 'config') or not sys.config.get('free_threading', False):
        print("Not running in free-threading mode")
        return False

    counter = 0
    counter_lock = threading.Lock()
    iterations = 10000
    threads_count = 4

    def increment_safe():
        nonlocal counter
        for _ in range(iterations):
            with counter_lock:
                counter += 1

    def increment_unsafe():
        nonlocal counter
        for _ in range(iterations):
            counter += 1  # This should be unsafe without GIL

    # Test with proper locking (should work)
    counter = 0
    threads = [threading.Thread(target=increment_safe) for _ in range(threads_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    safe_result = counter
    expected_safe = iterations * threads_count

    # Test without locking (may show race condition in free-threading)
    counter = 0
    threads = [threading.Thread(target=increment_unsafe) for _ in range(threads_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    unsafe_result = counter

    print(f"Safe counter: {safe_result} (expected: {expected_safe})")
    print(f"Unsafe counter: {unsafe_result} (expected: {expected_safe})")

    # In free-threading mode, unsafe result may be less than expected due to race
    # With GIL, unsafe might still be correct due to GIL protection (but not guaranteed)
    return safe_result == expected_safe
```

## Best Practices Summary

1. **Verify interpreter support** before deploying free-threading code
2. **Audit dependencies** for free-threading compatibility
3. **Use proper synchronization** for shared mutable state
4. **Prefer thread-safe data structures** from `queue` and `collections` modules
5. **Consider thread-local storage** for per-thread state
6. **Test thoroughly** under both threaded and free-threading modes
7. **Monitor performance** - free-threading may not benefit all workloads equally
8. **Gradual rollout** - enable in staging before production
9. **Document requirements** - specify free-threading Python 3.14+ in project docs
10. **Have fallback plan** - maintain compatibility with standard GIL mode

## Migration Strategy

### Phase 1: Assessment
- Verify Python 3.14+ availability
- Check dependency compatibility
- Identify CPU-bound bottlenecks in current codebase

### Phase 2: Development
- Develop/test in free-threading mode
- Add necessary synchronization primitives
- Update CI to test both modes

### Phase 3: Staging
- Deploy to staging environment with free-threading
- Monitor for race conditions and performance
- Validate dependency compatibility in staging

### Phase 4: Production
- Gradual rollout with feature flags
- Monitor key metrics (latency, error rates, throughput)
- Have rollback plan to GIL mode if needed

## Related References

- See [`references/async-patterns.md`](references/async-patterns.md) for comparison with asyncio approaches
- See [`references/type-hints.md`](references/type-hints.md) for PEP 695 generics that work well with free-threading
- See [`references/error-handling.md`](references/error-handling.md) for exception handling in threaded contexts
