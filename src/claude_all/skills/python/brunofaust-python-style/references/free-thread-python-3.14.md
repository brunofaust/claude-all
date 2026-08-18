# Free-thread Python 3.14 Reference

## Overview
Python 3.14 introduces a new execution model called *free-threading*, which allows for more efficient asynchronous programming by enabling multiple threads to run Python code simultaneously without the Global Interpreter Lock (GIL) restrictions.

## When to Use
Use free-threading when:
- Your application requires high concurrency and low latency.
- You are using native extensions that release the GIL.
- You want to leverage multiple CPU cores for compute-bound tasks.

## Pros and Cons
### Pros:
- **Parallelism**: True parallel execution of Python code using multiple threads.
- **Performance**: Improved performance for CPU-bound tasks.
- **Compatibility**: Works with libraries that release the GIL.

### Cons:
- **Complexity**: Increased code complexity due to thread synchronization needs.
- **Debugging**: Harder to debug concurrent code.
- **Resource Usage**: Higher memory usage due to multiple thread stacks.

## Implementation
To enable free-threading in Python 3.14:

1. **Set the `PYTHONP THREADS` environment variable:
   ```bash
export PYTHONP_THREADS=4  # Set the number of threads
```
2. **Use the `threading` module for concurrency:
   ```python
import threading

def worker()
    print('Thread is running')

threads = [threading.Thread(target=worker) for _ in range(4)]
for t in threads:
    t.start()
```
3. **Release the GIL in native extensions** (if applicable) using `PyEval_AcquireThreadState` and `PyEval_ReleaseThreadState`.

## Checking Dependency Compatibility
To verify if your dependencies are compatible with Python 3.14's free-threading:
1. **Check dependency documentation** for known issues with multi-threading.
2. **Run tests** with free-threading enabled to catch any synchronization issues.
3. **Use tools like `pytest-threadleak`** to detect thread leaks.

```bash
pytest --threadleak
