# Free-threading (PEP 703) — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

Consider free-threading builds of Python 3.14+ when:
- You have CPU-bound workloads that are limited by the GIL in the standard build.
- Your application uses multiple threads for parallelism (not just concurrency via asyncio).
- You have verified that your dependencies and C extensions are compatible with the GIL being disabled.
- You are running in a controlled environment where you can use the experimental free-threading build (not recommended for production critical systems without thorough testing).

## Core Concepts

Python 3.14 introduces an experimental free-threading build (PEP 703) where the Global Interpreter Lock (GIL) is made optional. In this build:
- The GIL can be disabled at runtime via the `PYTHON_GIL=0` environment flag or by using a special interpreter build.
- Multiple threads can execute Python bytecode in parallel, enabling true multi-core CPU utilization for pure Python code.
- Existing extension modules must be updated to be thread-safe when the GIL is disabled, or they will run with the GIL enabled by default for safety.

The free-threading build is intended for applications that:
1. Use heavy threading for CPU-bound tasks (e.g., scientific computing, data processing).
2. Have audited their dependencies for thread safety.
3. Can tolerate the experimental nature of the feature in 3.14.

## Implementation

### Using the Free-threading Build

1. **Obtain a free-threading capable Python 3.14 interpreter**:
   - Download from the official Python website (look for "free-threading" variant) or build from source with `--disable-gil`.
   - Verify the build: `python3.14 -c "import sys; print(sys._is_gil_enabled())"` should return `False` when GIL is disabled.

2. **Environment variable control**:
   - Set `PYTHON_GIL=0` in the environment to disable the GIL for the free-threading build.
   - Set `PYTHON_GIL=1` to force the GIL to be enabled (useful for testing compatibility).

3. **Code considerations**:
   - Most pure Python code that is thread-safe with the GIL will remain thread-safe without it, but shared mutable state must be protected by appropriate locks (e.g., `threading.Lock`).
   - The GIL's removal means that data races that were previously impossible due to the GIL can now occur. Review code for shared state access.
   - Use `sys._is_gil_enabled()` to conditionally adapt code if needed (though generally, the same locks work in both modes).

### Example: Adapting a CPU-bound function

```python
import threading
import sys
from typing import List

# Shared counter that requires protection
counter = 0
counter_lock = threading.Lock()

def increment_counter(times: int) -> None:
    global counter
    for _ in range(times):
        # Without the GIL, this increment is not atomic and requires a lock.
        with counter_lock:
            counter += 1

def worker(times: int) -> None:
    increment_counter(times)

def main() -> None:
    threads = [threading.Thread(target=worker, args=(100000,)) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(f"Final counter: {counter}")  # Expected: 1,000,000

if __name__ == "__main__":
    # Optionally check GIL status for logging/diagnostics
    if not sys._is_gil_enabled():
        print("Running with GIL disabled (free-threading)")
    else:
        print("Running with GIL enabled")
    main()
```

### Dependency Compatibility

To check if a dependency is compatible with free-threading:
1. **Pure Python packages**: Generally safe, but review for shared global state without locks.
2. **C extensions**: Must be updated to release the GIL during blocking operations or use fine-grained locking. Look for:
   - Documentation mentioning free-threading or PEP 703 support.
   - Wheels tagged with `abi3` and updated for Python 3.14 free-threading.
   - The presence of `Py_UNBLOCK_THREADS` macros in source (indicating GIL-aware releases).
3. **Testing**: Run your test suite with `PYTHON_GIL=0` and use tools like `faulthandler` to detect crashes or deadlocks.

### Checking GIL Status at Runtime

```python
import sys

def is_gil_enabled() -> bool:
    """Return True if the GIL is enabled, False if disabled (free-threading)."""
    return sys._is_gil_enabled()

# Usage
if is_gil_enabled():
    print("Operating in GIL mode")
else:
    print("Operating in free-threading mode")
```

## Pros and Cons

### Pros
- **True parallelism for CPU-bound Python code**: Multiple threads can utilize multiple cores simultaneously.
- **Better utilization of multi-core systems** for workloads that were previously limited by the GIL.
- **Compatibility with existing threading models**: Code that uses `threading.Thread` and locks can benefit without major rewrites.
- **Performance gains in specific scenarios**: Numerical simulations, data processing pipelines, and parallel algorithms.

### Cons
- **Experimental in Python 3.14**: Not recommended for production without thorough testing.
- **Incompatibility with some C extensions**: Extensions not updated for free-threading may crash or behave unexpectedly.
- **Increased complexity in reasoning about thread safety**: Developers must carefully audit shared state and locking.
- **Potential performance overhead**: Lock contention may increase in free-threading mode due to true parallelism.
- **Debugging challenges**: Data races and heisenbugs may manifest that were previously hidden by the GIL.

## When Not to Use

- Avoid free-threading for:
  - Applications heavily reliant on asyncio for concurrency (where the GIL is less of a bottleneck).
  - Environments where dependency compatibility cannot be verified.
  - Production systems requiring maximum stability without extensive validation.
  - Workloads that are I/O-bound rather than CPU-bound (the GIL is released during I/O anyway).

## Migration Strategy

1. **Start with testing**: Create a separate virtual environment with the free-threading build.
2. **Run your test suite** with `PYTHON_GIL=0` and look for failures.
3. **Audit dependencies**: Check each C extension for free-threading compatibility.
4. **Incrementally enable**: Begin with non-critical services or background workers.
5. **Monitor**: Use logging and metrics to detect anomalies in free-threading mode vs. GIL mode.

## Further Reading

- [PEP 703 -- Making the Global Interpreter Lock Optional in CPython](https://peps.python.org/pep-0703/)
- [Python 3.14 Free-threading Build Documentation](https://docs.python.org/3.14/whatsnew/3.14.html#free-threading-support)
- [Cython and Free-threading](https://cython.readthedocs.io/en/latest/src/userguide/free_threading.html)
