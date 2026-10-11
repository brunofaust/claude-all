# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

Python 3.14 introduces a free-threading build (PEP 703) that disables the Global Interpreter Lock (GIL), enabling true parallelism with threads for CPU-bound work.

**Use free-threading when:**
- You have CPU-bound pure Python workloads that can benefit from multi-core parallelism.
- You want to avoid the complexity of multiprocessing (pickling, process startup overhead) for shared-memory parallelism.
- Your workload consists of many threads that perform independent computations (embarrassingly parallel).
- You are building libraries or frameworks where you want to offer thread-based parallelism as an option.

**Avoid free-threading when:**
- Your workload is primarily I/O-bound (use `async/await` + `run_in_thread()` instead).
- You rely on C extensions that have not been updated for free-threading compatibility.
- You need strict determinism or reproducible timing (free-threading may introduce scheduling variability).
- You are extending existing code that assumes the GIL for thread safety (e.g., relies on atomic operations for shared state).

## Pros and Cons

### Pros
- **True parallelism for threads**: Multiple threads can execute Python bytecode simultaneously on multiple cores.
- **Lower overhead than multiprocessing**: No process startup cost, shared memory space, and faster communication via shared objects.
- **Simpler sharing of mutable state**: Threads can share objects directly without pickling/unpickling (though synchronization is still required).
- **Compatibility with existing thread-based code**: Code that correctly uses locks for thread safety will work without changes.
- **Integration with asyncio**: Free-threading works alongside asyncio; you can use threads for CPU-bound work and async for I/O-bound work.

### Cons
- **Performance overhead**: Fine-grained locking adds overhead, potentially slowing single-threaded execution.
- **C extension incompatibility**: Extensions that rely on the GIL for internal state may crash or behave incorrectly.
- **Increased complexity for shared state**: While sharing is easier, correct synchronization (locks, atomics) is still required to avoid race conditions.
- **Memory usage**: Each thread may have higher memory overhead due to duplicated interpreter state.
- **Tooling limitations**: Some profilers, debuggers, and tracing tools may not yet support free-threading builds.

### Comparison with Alternatives

| Approach                | Best For                          | Overhead | Shared State | Complexity |
|-------------------------|-----------------------------------|----------|--------------|------------|
| Free-threading threads  | CPU-bound pure Python             | Medium   | Direct (with locks) | Medium     |
| `InterpreterPoolExecutor` | CPU-bound pure Python (isolated)  | Low      | None (pickle only) | Low        |
| `run_in_thread()`       | Blocking I/O / C extensions       | Low      | None (pickle only) | Low        |
| Multiprocessing         | CPU-bound with heavy isolation    | High     | None (pickle)  | Medium     |
| Asyncio                 | I/O-bound, network, file ops      | Low      | None         | Low        |

## How to Implement

To use free-threading, you must run Python with a special build that disables the GIL. The language and standard library require no changes, but your code must be thread-safe for shared state.

### Basic Usage

Once you have a free-threading Python build (e.g., `python3.14t` or similar), you can use `threading.Thread` as usual:

```python
import threading
import time

def worker(n):
    """CPU-bound work that can run in parallel."""
    result = 0
    for i in range(n * 1000000):
        result += i
    return result

def main():
    threads = []
    results = []

    def worker_with_result(n, index):
        results.append((index, worker(n)))

    # Start 4 threads to work in parallel
    for i in range(4):
        t = threading.Thread(target=worker_with_result, args=(1000, i))
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    # Results are collected in order of completion
    results.sort(key=lambda x: x[0])
    print([r for _, r in results])

if __name__ == "__main__":
    main()
```

### Hybrid CPU + I/O Workloads

For applications that mix CPU-bound and I/O-bound work, combine free-threading with asyncio:

```python
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
import aiohttp

# Global thread pool for CPU-bound work
CPU_THREADPOOL = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="cpu-pool"
)

async def fetch_url(session, url):
    """I/O-bound work: fetch a URL asynchronously."""
    async with session.get(url) as resp:
        return await resp.text()

def process_data(data):
    """CPU-bound work: process the fetched data."""
    # Simulate CPU-intensive processing
    result = 0
    for char in data:
        result += ord(char)
    return result

async def main():
    urls = [
        "https://example.com/page1",
        "https://example.com/page2",
        "https://example.com/page3",
        "https://example.com/page4",
    ]

    async with aiohttp.ClientSession() as session:
        # Fetch all URLs concurrently (I/O-bound)
        html_pages = await asyncio.gather(
            *[fetch_url(session, url) for url in urls]
        )

        # Process the fetched data in parallel using threads
        loop = asyncio.get_running_loop()
        processing_tasks = [
            loop.run_in_executor(CPU_THREADPOOL, process_data, page)
            for page in html_pages
        ]
        results = await asyncio.gather(*processing_tasks)

        for url, result in zip(urls, results):
            print(f"{url}: {result}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Using InterpreterPoolExecutor (Alternative)

For CPU-bound pure Python where you want true isolation (no shared state), consider `InterpreterPoolExecutor` (available in Python 3.14+):

```python
from concurrent.futures import InterpreterPoolExecutor

def compute_factorial(n):
    """CPU-bound pure Python function."""
    if n < 2:
        return 1
    return n * compute_factorial(n - 1)

def main():
    numbers = [10, 12, 15, 18, 20, 22, 25]

    with InterpreterPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(compute_factorial, numbers))

    for n, result in zip(numbers, results):
        print(f"{n}! = {result}")

if __name__ == "__main__":
    main()
```

**Note**: `InterpreterPoolExecutor` isolates state between interpreters, so only picklable objects can be shared. Use free-threading threads when you need to share mutable state directly.

## How to Check Dependency Compatibility

Before deploying with free-threading, verify that your dependencies are compatible. Incompatible C extensions may crash, hang, or produce incorrect results.

### Checking for Free-Threading Support

1. **Look for the `free_threading` ABI tag**: Wheels compatible with free-threading are tagged with `abi3` and `free_threading` (or similar). Check with:
   ```bash
   pip show <package> | grep -i tag
   ```
   or inspect the wheel filename: `package-1.0.0-cp314-cp314t-free_threading-linux_x86_64.whl`.

2. **Check for the `Py_GIL_DISABLED` macro**: In source builds, look for this macro in the extension module's initialization:
   ```c
   #include <Python.h>

   static struct PyModuleDef moduledef = {
       PyModuleDef_HEAD_INIT,
       "mymodule",
       NULL,
       -1,
   };

   PyMODINIT_FUNC PyInit_mymodule(void) {
       PyObject *module = PyModule_Create(&moduledef);
       if (module == NULL) {
           return NULL;
       }

       #ifdef Py_GIL_DISABLED
       // Free-threading compatible initialization
       #endif

       return module;
   }
   ```

3. **Test import in a free-threading build**: The most reliable method is to try importing the module in a free-threading Python interpreter:
   ```bash
   python3.14t -c "import numpy; print('NumPy imported successfully')"
   ```

4. **Use `sys._is_gil_enabled()`**: At runtime, check if the GIL is disabled:
   ```python
   import sys
   if not sys._is_gil_enabled():
       print("Running in free-threading mode")
   else:
       print("Running with GIL enabled")
   ```

### Dependency Strategies

- **Pure Python packages**: These are always compatible with free-threading (no C extensions).
- **C extensions**: Prioritize packages that provide free-threading-compatible wheels. If unavailable, consider:
  - Using `run_in_thread()` for blocking calls (these extensions often release the GIL during I/O).
  - Switching to pure Python alternatives if available.
  - Building from source with free-threading support (if the project provides it).
- **Internal modules**: Audit your own C extensions and update them to be free-threading-safe:
  - Use per-interpreter state (PEP 3121) or module state.
  - Protect shared global state with locks (e.g., `pthread_mutex_t` or `PyThread_type_lock`).
  - Avoid relying on the GIL for atomicity of operations.

### Compatibility Checklist

Run this checklist in your free-threading environment:

- [ ] Import all top-level dependencies succeeds.
- [ ] Basic functionality of each dependency works as expected.
- [ ] Thread-safety guarantees hold (run concurrent stress tests if applicable).
- [ ] No increase in crash rate or incorrect results under load.
- [ ] Memory usage remains within expected bounds.
- [ ] Performance characteristics match expectations (single-threaded may be slower, multi-threaded faster for CPU-bound work).

### Handling Incompatible Dependencies

If a dependency is not free-threading-compatible:

1. **Isolate usage**: Run the incompatible code in a separate process using `multiprocessing` or `subprocess`.
2. **Wrapper thread with GIL**: Use a dedicated thread that acquires the GIL (if available via a compatibility layer) — but note this defeats the purpose of free-threading for that workload.
3. **Fallback to `InterpreterPoolExecutor`**: For CPU-bound pure Python, use interpreters to avoid sharing state.
4. **Contact maintainers**: Report the issue and request free-threading support.

## Related Documentation

- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines.
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms (e.g., raw `threading.Thread` may be banned in favor of managed pools).
- Consult `SKILL.md` for high-level skill conventions and recommendations.
