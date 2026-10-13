# Free-threading in Python 3.14 — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

Consider using the free-threaded build of Python 3.14 when:

- Your application is CPU-bound and can benefit from true parallelism across multiple CPU cores.
- You are using pure Python code or C extensions that have been updated to be thread-safe in a no-GIL environment.
- You are running workloads that are currently limited by the Global Interpreter Lock (GIL), such as multi-threaded numerical computations or data processing.
- You have evaluated that the potential performance gains outweigh the risks of using an experimental build and possible incompatibilities.

Avoid using the free-threaded build for:

- Applications that rely heavily on C extensions that have not been updated for free-threading (many popular libraries may not yet support it).
- Single-threaded applications where the free-threading build may introduce a small performance overhead.
- Environments where stability and broad compatibility are critical (the free-threading build is still experimental as of Python 3.14.0).

## Pros and Cons

### Pros

- **True parallelism**: Threads can run concurrently on multiple cores without the GIL bottleneck, leading to significant speedups for CPU-bound multi-threaded workloads.
- **Lower latency for I/O-bound tasks**: While the GIL already releases during I/O, free-threading can improve performance in mixed workloads by reducing contention.
- **Better utilization of modern hardware**: Makes better use of multi-core CPUs, especially in cloud and containerized environments with multiple vCPUs.
- **Compatibility with existing threaded code**: Existing code that uses threading for concurrency (not parallelism) will continue to work, and may see performance improvements if it was previously GIL-limited.

### Cons

- **Extension compatibility**: C extension modules must be updated to be thread-safe when the GIL is disabled. Many popular libraries (e.g., NumPy, Pandas, TensorFlow) may not yet provide free-threaded compatible wheels.
- **Potential performance overhead**: The free-threading build may have a small performance penalty for single-threaded code due to the overhead of fine-grained locking.
- **Experimental status**: As of Python 3.14.0, the free-threading build is still experimental and may have bugs or incomplete features.
- **Debugging complexity**: Debugging multi-threaded code is inherently more complex, and free-threading may expose race conditions that were previously hidden by the GIL.
- **Memory usage**: Each thread may have slightly higher memory overhead due to separate garbage collection states.

## How to Implement

### 1. Install a Free-Threaded Python Interpreter

You need to use a special build of Python 3.14 with the GIL disabled. Options include:

- **Building from source**: Download the Python 3.14 source and configure with `--disable-gil`.
  ```bash
  ./configure --disable-gil --prefix=/opt/python3.14-freethreaded
  make && make install
  ```
- **Using pre-built distributions**: Look for distributions that provide free-threading builds (e.g., from third-party providers or Docker images).
- **Docker**: Use a Docker image based on the free-threading build (e.g., `python:3.14t-free` or similar community images).

### 2. Create a Virtual Environment

Always use a virtual environment to isolate your project:
```bash
/opt/python3.14-freethreaded/bin/python -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

Install your project dependencies as usual, but ensure they are compatible with the free-threading build (see the next section).

### 4. Write Thread-Safe Code

When writing code that will run in a free-threaded environment:
- Avoid shared mutable state between threads, or use appropriate locking mechanisms (e.g., `threading.Lock`, `threading.RLock`, or `threading.Semaphore`).
- Be aware that the GIL no longer protects Python data structures, so operations on shared objects must be synchronized.
- Use thread-safe data structures from the `queue` module or `collections` module when appropriate.
- Prefer immutable data structures where possible to avoid the need for locking.

### 5. Leverage Parallelism

Use threading for CPU-bound tasks that can be parallelized:
```python
import threading
from concurrent.futures import ThreadPoolExecutor

def cpu_bound_task(data):
    # Perform computation that releases the GIL (in free-threading build)
    # or is pure Python and can run in parallel
    result = sum(x * x for x in data)
    return result

def main():
    data_chunks = [list(range(1000000)) for _ in range(8)]  # 8 chunks of data
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(cpu_bound_task, chunk) for chunk in data_chunks]
        results = [f.result() for f in futures]
    print(f"Results: {results}")

if __name__ == "__main__":
    main()
```

Note: In the free-threading build, pure Python code can now run in parallel on multiple cores without the GIL limitation.

## Checking Dependency Compatibility

To ensure your dependencies work with the free-threading build:

### 1. Check for Free-Threaded Wheels

When installing packages with `pip`, look for wheels tagged with `free_threaded` in the ABI tag, for example:
- `package-1.0.0-cp314-cp314-free_threaded_win_amd64.whl`
- `package-1.0.0-cp314-cp314-free_threaded_linux_x86_64.whl`

These wheels are specifically built for the free-threading ABI.

### 2. Use Compatibility Checking Tools

- **`pip` compatibility flags**: You can use `pip install --only-binary :all: --python-version 3.14 --implementation cp --abi free_threaded <package>` to attempt to install only free-threaded compatible wheels.
- **Audit your dependencies**: Use tools like `pipdeptree` or `pip check` to verify that all dependencies have free-threaded compatible versions.

### 3. Test in Isolation

Before deploying, test your application in a free-threaded environment with a subset of your dependencies:
1. Create a fresh virtual environment with the free-threaded Python.
2. Install your dependencies one by one, starting with the most critical.
3. Run your test suite to catch any crashes or incorrect behavior due to threading issues.
4. Pay special attention to C extensions and libraries that perform low-level operations.

### 4. Monitor for Crashes and Incorrect Behavior

In a free-threaded build, incompatible C extensions may cause:
- Segmentation faults (crashes)
- Incorrect results due to race conditions
- Deadlocks or hangs

If you encounter crashes, check if the extension has a free-threaded compatible version or consider contributing to its porting.

### 5. Stay Updated

Keep track of the progress of popular libraries toward free-threading compatibility:
- Follow the Python Discord server or mailing lists for updates.
- Check the GitHub repositories of your dependencies for branches or tags related to free-threading.
- Participate in the community effort to port libraries to the free-threading build.

## Example: Verifying Extension Compatibility

You can check if a module is compatible with the free-threading build by attempting to import it and checking for the presence of the `free_threaded` flag in the ABI tag:

```python
import sys
import sysconfig

def is_free_threaded_build():
    """Check if the current Python interpreter is a free-threading build."""
    # In Python 3.14+, the ABI tag includes 'free_threaded' for free-threading builds
    abi_tag = sysconfig.get_config_var('SOABI')
    return 'free_threaded' in abi_tag

if is_free_threaded_build():
    print("Running in free-threading build")
else:
    print("Running in regular build")

# Example: Check a specific extension
try:
    import numpy
    print(f"NumPy version: {numpy.__version__}")
    # If NumPy has a free-threaded build, it should import without crashing
except ImportError as e:
    print(f"Failed to import NumPy: {e}")
```

## Conclusion

The free-threading build of Python 3.14 offers exciting opportunities for true parallelism in multi-threaded Python applications. However, it requires careful consideration of dependency compatibility and thread-safety. By following the guidelines above, you can evaluate whether the free-threading build is suitable for your project and take the necessary steps to adopt it safely.
