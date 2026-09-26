# Free-threading (GIL-less) Python — full reference

> Reference page for the `brunofaust-python-style` skill. The main `SKILL.md` keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces an optional **free-threading build** (also known as the "no-GIL" build) that disables the Global Interpreter Lock (GIL) by default. This allows multiple threads to execute Python bytecode in parallel, enabling true multi-threaded CPU-bound parallelism within a single Python process.

The free-threading build is available via the `python3.14t` executable (or similar) when Python is compiled with the `--disable-gil` flag. At runtime, the GIL behavior can also be toggled via the `PYTHON_GIL=0` environment variable or the `-X gil=0` flag (if the interpreter supports it).

**Note:** The free-threading build is **not** the default; you must specifically install or build a free-threading-capable Python interpreter.

## When to Use

Consider free-threading when you have:

- **CPU-bound workloads** that are parallelizable across multiple cores (e.g., numerical simulations, data processing, image/video processing).
- Workloads that currently use `multiprocessing` to bypass the GIL but suffer from high inter-process communication (IPC) overhead.
- Scenarios where shared memory access patterns are beneficial (e.g., large in-memory data structures that would be costly to duplicate across processes).
- Applications where you already use threading for I/O-bound work and want to extend parallelism to CPU-bound phases without rewriting to use processes or subinterpreters.

**Do not use free-threading for:**
- Purely I/O-bound workloads (async/await with `asyncio` is more appropriate).
- Workloads that rely on C extensions that are not GIL-safe (many popular libraries like NumPy, Pandas, etc., may still hold the GIL during C-coded sections).
- Situations where thread safety becomes a concern (free-threading increases the need for proper locking or use of thread-safe data structures).

## Pros and Cons

### Pros

- **True parallelism** for CPU-bound Python code without the overhead of process creation and IPC.
- **Lower memory footprint** compared to `multiprocessing` (no need to duplicate Python objects across processes).
- **Simpler sharing** of mutable state between threads (though this requires careful synchronization).
- **Compatibility** with existing threading-based code (e.g., code that uses `threading.Thread` or `concurrent.futures.ThreadPoolExecutor`).

### Cons

- **Increased complexity** in writing thread-safe code (race conditions, deadlocks, etc.).
- **Limited library compatibility** — many C extensions still acquire the GIL or are not thread-safe for concurrent use.
- **Potential for slower single-threaded performance** due to the overhead of fine-grained locking (though efforts are made to minimize this).
- **Debugging challenges** — race conditions and other concurrency bugs can be harder to reproduce and diagnose.
- **Platform support** — free-threading may not be available in all environments (e.g., certain PaaS offerings, container images, or embedded distributions). Typically available in self-hosted, ECS/EC2, VM, or on-prem setups.

## Implementation

### Enabling Free-threading

1. **Obtain a free-threading-capable Python interpreter**:
   - Build Python from source with `./configure --disable-gil` (and optionally `--with-pydebug` for debugging).
   - Use distributions that provide free-threading builds (e.g., certain versions of conda-forge, or community-maintained Docker images).
   - Check for `python3.14t` or similar aliases in your package manager.

2. **Verify the build**:
   ```python
   import sys
   import _thread
   print("Free-threading enabled:", sys._is_gil_enabled() == False)  # Python 3.14+
   # Or check for the presence of the gil flag in sys.flags
   ```

### Basic Usage

With a free-threading build, existing threading APIs work as expected but now allow parallel execution of Python bytecode:

```python
import threading
import time

def cpu_bound_work(n):
    total = 0
    for i in range(n):
        total += i * i
    return total

def worker():
    result = cpu_bound_work(10_000_000)
    print(f"Worker result: {result}")

# Launch multiple threads
threads = []
for _ in range(4):
    t = threading.Thread(target=worker)
    t.start()
    threads.append(t)

for t in threads:
    t.join()
```

### Using `concurrent.futures`

The `ThreadPoolExecutor` from `concurrent.futures` can also leverage free-threading:

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

def count_primes(start, end):
    return sum(1 for i in range(start, end) if is_prime(i))

with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [
        executor.submit(count_primes, 0, 250_000),
        executor.submit(count_primes, 250_000, 500_000),
        executor.submit(count_primes, 500_000, 750_000),
        executor.submit(count_primes, 750_000, 1_000_000),
    ]
    results = [f.result() for f in futures]
    print(f"Total primes: {sum(results)}")
```

### Interaction with Asyncio

Free-threading does not change the asyncio model; you still use `asyncio.run()` (or `uvloop.run()`) for async entry points. However, you can now combine free-threading threads with asyncio for hybrid workloads:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

async def main():
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=4) as pool:
        # Run blocking CPU-bound work in threads without blocking the event loop
        result = await loop.run_in_executor(pool, cpu_bound_work, 10_000_000)
        print(f"Result: {result}")

asyncio.run(main())
```

### Comparison with Subinterpreters (PEP 734)

Python 3.14 also includes `InterpreterPoolExecutor` (from `concurrent.futures`) which uses subinterpreters to achieve parallelism with separate GILs per interpreter. Consider:

- **Free-threading**: Single interpreter, no GIL, shared memory (requires explicit synchronization).
- **Subinterpreters**: Multiple interpreters, each with its own GIL, limited sharing (only via shared memory or explicit communication channels).

Choose free-threading when you need low-overhead sharing of complex data structures; choose subinterpreters when you prefer isolation and minimal shared state.

## Checking Dependency Compatibility

Before adopting free-threading, verify that your dependencies are safe for concurrent use:

1. **Pure Python modules**: Generally safe (they rely on the GIL for atomicity of bytecode, but without the GIL, you must ensure thread safety yourself via locks or using thread-safe data structures).

2. **C extensions**:
   - Check if the extension documents its threading behavior.
   - Look for releases that explicitly state they are "free-threading compatible" or "GIL-free".
   - Test with a simple multi-threaded script that calls the extension from multiple threads.
   - Be aware that some extensions may release the GIL during long-running operations (e.g., NumPy array operations) but still require the GIL for others.

3. **Common libraries status (as of Python 3.14 release)**:
   - **NumPy**: Many operations release the GIL, but some internal operations may still hold it. Check the latest release notes.
   - **Pandas**: Similar to NumPy; built on NumPy.
   - **Requests**: The library is I/O-bound and releases the GIL during network waits; however, internal use of urllib3 may have GIL considerations.
   - **boto3 / aiobotocore**: Primarily I/O-bound; safe for free-threading as network calls release the GIL.
   - **Polars**: Built in Rust; designed for parallelism and releases the GIL appropriately.
   - **DeltaTable**: Involves Rust FFI; check for thread‑safety guarantees.

4. **Tools to help**:
   - Use `sys._is_gil_enabled()` (available in free-threading builds) to verify the runtime state.
   - Consider running your test suite with the free-threading build to catch threading‑related issues early.
   - Utilize static analysis tools that detect potential race conditions (though these are limited).

## Best Practices

- **Prefer immutability**: Share immutable data between threads whenever possible to avoid synchronization overhead.
- **Use thread-safe data structures**: `queue.Queue`, `collections.deque` (with appropriate locking), or `multiprocessing.Manager`‑style proxies if needed.
- **Minimize shared mutable state**: Design your concurrent work to operate on independent partitions of data.
- **Profile both single‑threaded and multi‑threaded performance**: Ensure that the overhead of locking does not outweigh the gains from parallelism.
- **Handle exceptions properly**: Exceptions in threads must be captured and communicated to the main thread (e.g., via `Future` or custom result queues).
- **Set realistic thread counts**: More threads than CPU cores can lead to increased context‑switching overhead; consider the workload characteristics (CPU‑bound vs. mixed).
- **Document assumptions**: Clearly mark sections of code that assume free‑threading behavior or require thread‑safety precautions.

## Platform Support

Free‑threading is primarily beneficial in environments where you control the Python runtime:

- **Recommended**: Self‑hosted servers, ECS/EC2 instances, virtual machines, on‑premises clusters, CI/CD runners with custom images.
- **Limited or unavailable**:
  - AWS Lambda (currently uses Amazon Linux with standard Python builds; no free‑threading option).
  - AWS Fargate (depends on the container image; you can bring your own free‑threading‑capable image if supported).
  - Google Cloud Functions, Azure Functions (similar constraints; check provider documentation).
  - Platform‑as‑a‑Service (PaaS) offerings that lock the Python runtime.

Always verify that your target deployment environment permits the use of a custom or free‑threading‑capable Python interpreter before adopting this approach.

## When to Stick with Alternatives

- For **I/O‑bound** workloads, continue to use `asyncio` with `async` libraries (e.g., `aiohttp`, `aiobotocore`).
- For **CPU‑bound** workloads where library compatibility is a concern, consider `multiprocessing` or `ProcessPoolExecutor` (despite higher overhead).
- For **CPU‑bound** workloads that require isolation and minimal sharing, evaluate `InterpreterPoolExecutor` (subinterpreters) as a safer alternative.
- For **embedding Python** in applications where threading complexity is undesirable, consider async‑only designs or offloading to external services.

## Example: Numerical Integration with Free‑threading

Here’s a simple example demonstrating parallel numerical integration using free‑threading:

```python
import threading
import math

def integrate_segment(f, a, b, n_steps):
    """Integrate f from a to b using the midpoint rule."""
    dx = (b - a) / n_steps
    total = 0.0
    for i in range(n_steps):
        x = a + (i + 0.5) * dx
        total += f(x) * dx
    return total

def parallel_integrate(f, a, b, n_steps, n_threads=4):
    """Parallel integration using free‑threading."""
    step_per_thread = n_steps // n_threads
    threads = []
    results = [0.0] * n_threads

    def worker(thread_id, start, end):
        results[thread_id] = integrate_segment(f, start, end, step_per_thread)

    step_size = (b - a) / n_threads
    for i in range(n_threads):
        start = a + i * step_size
        end = start + step_size
        t = threading.Thread(target=worker, args=(i, start, end))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    return sum(results)

# Example: integrate sin(x) from 0 to pi
result = parallel_integrate(math.sin, 0, math.pi, 10_000_000)
print(f"Integral of sin(x) from 0 to pi: {result}")  # Should be close to 2.0
```

This example shows how free‑threading can be used to parallelize a CPU‑bound numerical computation without the process‑creation overhead of `multiprocessing`.

---
