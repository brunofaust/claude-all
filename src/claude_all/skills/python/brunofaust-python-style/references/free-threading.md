# brunofaust-python-style

## Python 3.14 Free-Thread Feature Reference

### When to Use Free-Thread
Free-threading in Python 3.14 allows for more efficient concurrent execution by enabling multiple threads to execute Python bytecode simultaneously. This feature is particularly useful for:

- **I/O-bound applications**: When your code spends significant time waiting for external resources (network, disk, etc.), free-threading can improve throughput.
- **CPU-bound applications with external concurrency**: If your application uses external libraries or processes that handle parallelism (e.g., NumPy operations), free-threading can help leverage those capabilities more effectively.

### Pros and Cons
| Aspect | Pro | Con |
|-------|-----|-----|
| **Performance** | Improved throughput for I/O-bound and externally parallel workloads | Minimal gain for pure Python CPU-bound tasks
| **Complexity** | Simplifies threading management | Requires understanding of threading risks (e.g., race conditions)
| **Compatibility** | Works with existing threading libraries | May require code adjustments for thread safety

### How to Implement Free-Thread
1. **Enable Free-Thread Mode**:
   Set the `PYTHONGUARD_DISABLE` environment variable to `1` before running your Python application:
   ```bash
   PYTHONGUARD_DISABLE=1 python -m myapp
   ```
   This disables the Global Interpreter Lock (GIL), allowing free-threading.

2. **Thread Safety Considerations**:
   - Use `threading` module primitives (locks, ThreadLocal, etc.) to protect shared resources.
   - Consider using `concurrent.futures.ThreadPoolExecutor` for structured concurrency.

### Checking Dependency Compatibility
To ensure your dependencies work with free-threaded Python:

1. **Review Dependency Documentation**: Confirm that libraries are thread-safe or explicitly support free-threading.
2. **Test with `PYTHONGUARD_DISABLE=1`**: Run your test suite with free-threading enabled to catch potential issues.
3. **Watch for Known Issues**: Some libraries (e.g., CPython extensions not updated for 3.14) may have compatibility quirks.
