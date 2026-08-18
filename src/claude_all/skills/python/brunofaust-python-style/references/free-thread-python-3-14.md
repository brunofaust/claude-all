# Python 3.14 Free-Thread Feature Reference

## Overview
The free-thread feature in Python 3.14 allows specific built-in functions and modules to execute in a non-GIL (Global Interpreter Lock) context, enabling better concurrency and performance for certain operations. This document provides guidance on when to use, how to implement, and how to verify compatibility with this feature.

## Use Cases

### Recommended Scenarios
- **CPU-bound operations in standard library**: Functions like `os.walk()`, `os.scandir()`, and `shutil.copytree()` can benefit from free-thread execution when dealing with large filesystem operations.
- **Async code with `asyncio`**: Free-thread can be used to offload blocking operations without starving the main event loop.

### Not Recommended Scenarios
- **Code requiring GIL**: If your code explicitly needs GIL for thread synchronization.
- **Legacy extensions**: C extensions not designed for free-thread execution may cause crashes or data corruption.

## Pros and Cons

### Pros
- **Improved performance**: For I/O and filesystem operations, especially on systems with multiple cores.
- **Better concurrency**: Reduces contention for the GIL in mixed workloads.

### Cons
- **Complexity**: Requires careful handling of thread-safe practices.
- **Compatibility issues**: Older C extensions may not work correctly.

## Implementation Guide

### Enabling Free-Thread Execution
To use free-thread execution, ensure your code is structured to allow it:

```python
# Example: Using os.walk with free-thread
import os

# This will use free-thread if available
for root, dirs, files in os.walk("/some/path()):
    # Process files
    pass
```

### Checking Support
Ensure your Python environment supports free-thread execution:

```python
import sys

if sys.version_info >= (3, 14):
    print("Free-thread supported")
else:
    print("Free-thread not supported")
```

## Compatibility Checks

### Dependency Verification
1. **Check dependency versions**: Ensure all third-party libraries are compatible with Python 3.14 and free-thread execution.
2. **Test in a sandbox environment**: Before deploying to production, test your application thoroughly.
3. **Use isolation**: Consider using Docker or virtual environments to isolate and test free-thread compatibility.

### Manual Checks for C Extensions
For C extensions:
- Review the extension's documentation for free-thread support.
- Use tools like `gdb` or `valgrind` to detect thread-safety issues.

### Automated Checks
Implement automated tests that verify:
- The version of Python being used is 3.14 or higher.
- Critical paths using free-thread execute without crashes or deadlocks.

This reference will be reviewed and updated as more experience with Python 3.14 free-thread feature is gained in the codebase.
