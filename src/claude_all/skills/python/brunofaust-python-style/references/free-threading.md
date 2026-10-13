# Python 3.14 Free-Threading Reference

## When to Use Free-Threading

Python 3.14 introduces an optional Global Interpreter Lock (GIL) mode, allowing threads to run in parallel for CPU-bound workloads. Consider using free-threading when:

- You have CPU-bound tasks that can be parallelized across multiple cores
- You prefer threading over multiprocessing for simpler shared memory access
- Your workload involves many threads performing computational work (not just I/O)
- You are building applications where process-based parallelism introduces too much overhead
- You are developing extensions that need to take advantage of multiple cores without process boundaries

Free-threading is **not** beneficial for:
- Pure I/O-bound workloads (where asyncio or regular threading with GIL is sufficient)
- Workloads requiring minimal shared state (where multiprocessing avoids complexity)
- Environments where thread safety is difficult to maintain

## Pros and Cons

### Pros
- **True parallelism**: Multiple threads can execute Python bytecode simultaneously
- **Lower overhead**: Compared to multiprocessing, avoids process creation and IPC costs
- **Shared memory**: Threads share memory space naturally, simplifying data sharing
- **Incremental adoption**: Can be enabled per-interpreter without changing application structure
- **Compatibility**: Existing threading code works; only extensions need updates for thread safety

### Cons
- **Thread safety burden**: Developers must ensure shared state is properly synchronized
- **Extension compatibility**: C extensions must be updated to work without the GIL
- **Potential performance regression**: Single-threaded performance may slightly decrease due to GIL overhead when enabled
- **Debugging complexity**: Race conditions and deadlocks are harder to diagnose
- **Memory overhead**: Per-interpreter state increases when running multiple subinterpreters

## How to Implement

### Building Python with Free-Threading
To use free-threading, build Python with the `--disable-gil` flag:
```bash
./configure --disable-gil
make
make install
```
This creates a Python interpreter where the GIL is optional and can be disabled at runtime.

### Runtime Check
Check if free-threading is available:
```python
import sys
print(sys._is_gil_enabled())  # Returns False if GIL is disabled
```

### Using Threads
Standard threading module works unchanged:
```python
import threading
import time

def worker():
    # CPU-intensive work
    result = sum(i * i for i in range(1000000))
    return result

threads = []
for _ in range(4):
    t = threading.Thread(target=worker)
    t.start()
    threads.append(t)

for t in threads:
    t.join()
```

### Extension Development
For C extensions, use the new macros:
```c
#include "Python.h"

#ifdef Py_GIL_DISABLED
/* Thread-safe code when GIL is disabled */
#else
/* Code that assumes GIL protection */
#endif
```
Extensions should:
- Avoid holding mutable shared state without locks
- Use Py_BEGIN_ALLOW_THREADS/Py_END_ALLOW_THREADS appropriately
- Test with both GIL-enabled and disabled builds

## Checking Dependency Compatibility

### 1. Package Metadata
Look for packages that declare free-threading compatibility:
- Check PyPI classifiers: `Framework :: CPython :: 3.14 :: FreeThreading`
- Examine package documentation for mentions of `--disable-gil` or free-threading support

### 2. Runtime Inspection
Check if a module is safe for free-threading:
```python
import sys
import some_extension

# Check if extension was built with free-threading support
if hasattr(some_extension, '__free_threading__'):
    print("Extension supports free-threading")
else:
    print("Extension may require GIL")
```

### 3. Testing Strategy
- Run your test suite with both GIL-enabled and disabled Python builds
- Use tools like `faulthandler` to detect crashes
- Stress test with multiple threads to uncover race conditions
- Consider using thread sanitizers (TSAN) for C extensions

### 4. Community Resources
- Monitor the [python-capi](https://discuss.python.org/c/core-dev/10) forum for compatibility updates
- Check extension maintainers' statements about free-threading support
- Consult the [Python 3.14 porting guide](https://docs.python.org/3.14/whatsnew/3.14.html#free-threading-support)

## Best Practices

1. **Start with profiling**: Verify your workload is CPU-bound and benefits from parallelism
2. **Gradual adoption**: Enable free-threading in development/test environments first
3. **Use appropriate synchronization**: Prefer threading.Lock, RLock, or threading.Semaphore over low-level primitives
4. **Avoid shared mutable state**: Use thread-local storage or message passing when possible
5. **Monitor performance**: Measure both throughput and latency to ensure benefits outweigh overhead
6. **Document assumptions**: Clearly mark code sections that require free-threading or GIL-specific behavior

## Further Reading
- [PEP 703 -- Making the Global Interpreter Lock Optional in CPython](https://peps.python.org/pep-0703/)
- [Python 3.14 Release Schedule](https://devguide.python.org/versions/3.14/)
- [Threading Documentation](https://docs.python.org/3/library/threading.html)
- [C API Reference for Thread State](https://docs.python.org/3/c-api/thread.html)
