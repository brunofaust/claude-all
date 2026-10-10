# Free-threading (GIL-less) Python — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

- **Python 3.14 only** — requires building Python with the `--disable-gil` flag (free-threading build).
- **CPU-bound workloads** that can benefit from true parallelism across multiple cores.
- **Applications where the GIL is a bottleneck** and you have tested that your dependencies work in the free-threading mode.
- **Not for I/O-bound workloads** — asyncio and threading already work well for I/O; free-threading is for CPU-bound parallelism.

## Core Concepts

### What is Free-threading?

Python 3.14 introduces an optional build mode that removes the Global Interpreter Lock (GIL), allowing multiple threads to execute Python bytecode in parallel. This is known as "free-threading" or "GIL-less" Python.

- The GIL is still present by default; to use free-threading, you must use a special build of Python 3.14 configured with `--disable-gil`.
- In free-threading mode, multiple threads can run Python code simultaneously, enabling true multi-core parallelism for CPU-bound Python code.
- Extension modules must be updated to be thread-safe and compatible with free-threading. Many popular packages now offer free-threading compatible wheels.

### Pros

- **True parallelism** for CPU-bound Python code without needing multiprocessing.
- **Lower overhead** than multiprocessing (no pickling/inter-process communication).
- **Simpler sharing** of mutable state between threads (with proper locking).
- **Better utilization** of multi-core CPUs for Python workloads.

### Cons

- **Only available in Python 3.14** with a special build.
- **Extension compatibility required** — many C extensions must be updated to be thread-safe and release the GIL appropriately.
- **Potential for new bugs** — race conditions that were hidden by the GIL may surface.
- **Performance overhead** in single-threaded scenarios due to finer-grained locking.
- **Not all packages support it yet** — check compatibility before adopting.

## How to Implement

### 1. Install a Free-threading Python Build

You need Python 3.14 built with the `--disable-gil` flag. Options:

- **Compile from source**:
  ```bash
  ./configure --disable-gil --enable-optimizations
  make -j$(nproc)
  sudo make altinstall
  ```

- **Use a distribution** that provides free-threading builds (e.g., some Linux distributions, or via `pyenv` with the `free-threading` variant).

- **Use Docker** images that provide free-threading Python 3.14.

### 2. Update Your Code for Free-threading

- **Use threading instead of multiprocessing** for CPU-bound parallelism where appropriate.
- **Ensure thread safety** for shared mutable state — use locks (`threading.Lock`, `threading.RLock`, `threading.Semaphore`) or use thread-safe data structures.
- **Avoid shared mutable state** when possible — use immutable data or message passing.
- **Consider using `concurrent.futures.ThreadPoolExecutor`** for simple parallelism.

### 3. Example: CPU-bound Parallel Processing

```python
import threading
from concurrent.futures import ThreadPoolExecutor
import math

def is_prime(n: int) -> bool:
    """CPU-bound function to check if a number is prime."""
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
    """Count primes in a range [start, end)."""
    return sum(1 for n in range(start, end) if is_prime(n))

def main() -> None:
    """Example using ThreadPoolExecutor for parallel prime counting."""
    total_range = (0, 1_000_000)
    num_workers = 4
    chunk_size = (total_range[1] - total_range[0]) // num_workers

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = []
        for i in range(num_workers):
            chunk_start = total_range[0] + i * chunk_size
            chunk_end = chunk_start + chunk_size if i < num_workers - 1 else total_range[1]
            futures.append(
                executor.submit(count_primes_in_range, chunk_start, chunk_end)
            )

        total_primes = sum(f.result() for f in futures)
        print(f"Total primes found: {total_primes}")

if __name__ == "__main__":
    main()
```

### 4. Using InterpreterPoolExecutor (Alternative)

Python 3.14 also introduces `InterpreterPoolExecutor` (PEP 734) which uses subinterpreters for parallelism without sharing the GIL. This is an alternative to threading for CPU-bound work that doesn't need to share mutable state.

```python
from concurrent.futures import InterpreterPoolExecutor

def compute_square(x: int) -> int:
    """CPU-bound computation."""
    return x * x

with InterpreterPoolExecutor() as executor:
    results = list(executor.map(compute_square, range(100)))
```

Note: `InterpreterPoolExecutor` has limitations on shareable types (only `str | bytes | int | float | bool | None | tuple | memoryview` can be shared without pickling).

## How to Check if Dependencies are Compatible

### 1. Check for Free-threading Wheels

When installing packages, look for wheels labeled with `free_threaded` or `ft` in the filename, or check the package's documentation for free-threading support.

Example:
```bash
pip show <package>
```
Look for metadata indicating free-threading compatibility.

### 2. Use the `freethreading` Compatibility Checker

Some tools can help check compatibility. For example, the `freethreading` PyPI package provides a script to check if a package is free-threading safe.

### 3. Test in Isolation

- Create a virtual environment with your free-threading Python build.
- Install your dependencies.
- Run your test suite to see if any tests fail due to threading issues.
- Look for symptoms like crashes, hangs, or incorrect results that may indicate race conditions.

### 4. Check Extension Modules

If you use C extensions or Cython modules, verify that they have been updated for free-threading. The extension must:
- Properly manage the GIL (if using the GIL-enabled API) or use the new per-interpreter GIL APIs.
- Be thread-safe when called from multiple threads simultaneously.

### 5. Monitor for Runtime Issues

Even if dependencies claim compatibility, monitor your application for:
- Increased crash rates.
- Deadlocks or livelocks.
- Performance degradation (due to lock contention).
- Incorrect results (race conditions).

## Best Practices Summary

1. **Profile first** — ensure the GIL is actually a bottleneck in your application.
2. **Start with a subset** — enable free-threading for non-critical services first.
3. **Use thread-safe data structures** — prefer `queue.Queue`, `collections.deque` with locks, or `multiprocessing.Manager` for shared state when needed.
4. **Avoid global mutable state** — use dependency injection or thread-local storage where appropriate.
5. **Consider alternatives** — for many CPU-bound tasks, multiprocessing or asyncio with `run_in_thread` may still be simpler and more compatible.
6. **Keep compatibility** — maintain dual compatibility with GIL-enabled Python if you need to support older versions.
7. **Update dependencies regularly** — free-threading support is improving rapidly in the ecosystem.

## References

- [PEP 703: Making the Global Interpreter Lock Optional in CPython](https://peps.python.org/pep-0703/)
- [Python 3.14 Free-threading Documentation](https://docs.python.org/3.14/whatsnew/3.14.html#free-threading-support)
- [Cython Free-threading Support](https://cython.readthedocs.io/en/latest/src/userguide/free_threading.html)
