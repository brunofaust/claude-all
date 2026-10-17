# Free-threading (PEP 703) — Python 3.14

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

Consider using Python 3.14 free-threading builds when:

- You have CPU-bound Python workloads that could benefit from true parallelism
- Your application spends significant time in Python code (not just waiting for I/O)
- You're currently using threading but hitting GIL limitations
- You want to avoid the complexity of multiprocessing (pickling, memory overhead)
- Your dependencies are compatible with free-threading builds
- You're building new applications or can upgrade existing ones to Python 3.14+

## Pros and Cons

### Pros

- **True parallelism**: Multiple threads can execute Python bytecode simultaneously
- **Lower overhead**: Less memory and startup overhead compared to multiprocessing
- **Shared memory**: Easy sharing of objects between threads without pickling/unpickling
- **Familiar threading model**: Uses standard threading.Thread API developers already know
- **Better utilization**: Can fully utilize multi-core CPUs for Python workloads
- **Gradual adoption**: Can run existing code unchanged in free-threading mode

### Cons

- **Dependency compatibility**: All C extensions and dependencies must be free-threading compatible
- **Potential race conditions**: Existing thread-unsafe code may manifest issues more readily
- **Debugging complexity**: More complex debugging due to actual parallel execution
- **Limited availability**: Only available in Python 3.14+ free-threading builds
- **Performance variance**: Some workloads may see slower performance due to increased contention
- **Ecosystem maturity**: Still early adoption phase, fewer libraries certified compatible

## How to Implement

### 1. Install Python 3.14 Free-threading Build

```bash
# Using uv (recommended)
uv python install 3.14.0 --free-threaded

# Or using python.org installers
# Download from: https://www.python.org/downloads/
# Look for "Python 3.14.0 - free-threading build"

# Verify installation
python3.14 -V
# Should show: Python 3.14.0 (free-threading)
```

### 2. Create Virtual Environment

```bash
uv venv --python 3.14.0 --free-threaded
source .venv/bin/activate
```

### 3. Basic Usage (No Code Changes Required)

Existing threading code works unchanged:

```python
import threading
import time

def worker(name):
    print(f"Worker {name} starting")
    # CPU-bound work
    result = sum(i * i for i in range(100000))
    print(f"Worker {name} finished: {result}")

# Run multiple threads in parallel
threads = []
for i in range(4):
    t = threading.Thread(target=worker, args=(i,))
    threads.append(t)
    t.start()

for t in threads:
    t.join()
```

### 4. Detecting Free-threading Mode

```python
import sys
import threading

def is_freethreading_build():
    """Check if running in a free-threading Python build."""
    return hasattr(sys, 'freethreading') and sys.freethreading

# Or check thread limit (should be 0 in free-threading builds)
def has_gil():
    """Return True if GIL is enabled, False if disabled."""
    return threading.get_malloc_lock() is not None

# Usage
if is_freethreading_build():
    print("Running in free-threading mode - true parallelism available")
else:
    print("Running with GIL - threads limited to single CPU core")
```

### 5. Thread Safety Considerations

Review your code for thread safety:

```python
# Avoid shared mutable state without proper synchronization
import threading
from threading import Lock

# Good: Use locks for shared state
counter = 0
counter_lock = Lock()

def safe_increment():
    global counter
    with counter_lock:
        counter += 1

# Better: Use thread-local storage when possible
local_data = threading.local()

def worker_init():
    local_data.value = 0

def worker():
    local_data.value += 1  # Each thread has its own copy
```

## How to Check Dependencies Compatibility

### 1. Check Python Version and Build

```python
import platform
import sys

def check_freethreading_support():
    """Verify Python 3.14+ free-threading build."""
    version_info = sys.version_info
    is_freethreading = hasattr(sys, 'freethreading') and sys.freethreading

    print(f"Python version: {version_info.major}.{version_info.minor}.{version_info.micro}")
    print(f"Free-threading build: {is_freethreading}")
    print(f"Platform: {platform.platform()}")

    return version_info >= (3, 14) and is_freethreading

# Usage
if not check_freethreading_support():
    print("Warning: Not running in Python 3.14+ free-threading build")
    print("Free-threading features will not be available")
```

### 2. Check Individual Dependencies

```bash
# Method 1: Check if package has free-threading wheel
pip show <package-name> | grep -i "free-threading\|no-gil"

# Method 2: Try importing in free-threading environment
python3.14 -c "import numpy; print('NumPy imported successfully')"

# Method 3: Check package documentation or PyPI classifiers
# Look for: "Free threading", "No GIL", "PEP 703"

# Method 4: Use compatibility checking tools (emerging)
# Example: pip install freethreading-checker
# freethreading-checker check requirements.txt
```

### 3. Commonly Compatible Libraries (as of Python 3.14 release)

**Likely compatible:**
- Pure Python packages (no C extensions)
- NumPy (experimental free-threading builds available)
- Pandas (building on NumPy compatibility)
- Requests, urllib3 (HTTP libraries)
- Pillow (PIL fork)
- Many standard library modules

**May require verification:**
- Libraries with custom C extensions
- Database drivers (psycopg2, mysql-client, etc.)
- GUI frameworks (tkinter, PyQt, etc.)
- Scientific computing libraries (SciPy, matplotlib, etc.)
- Cryptography libraries

### 4. Testing Strategy

```python
# Add to your test suite to verify free-threading compatibility
import sys
import threading
import time
import subprocess

def test_freethreading_basic():
    """Basic test that free-threading is working."""
    if not (hasattr(sys, 'freethreading') and sys.freethreading):
        print("SKIP: Not running in free-threading build")
        return True

    results = []
    def worker(n):
        # CPU-intensive work
        total = sum(i * i for i in range(50000))
        results.append(total)

    # Launch multiple threads
    threads = [
        threading.Thread(target=worker, args=(i,))
        for i in range(4)
    ]

    start = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - start

    # In free-threading build, should complete faster than sequential
    # (This is a simplified check - real testing needs more sophistication)
    print(f"Free-threading test completed in {elapsed:.2f}s")
    return len(results) == 4

# Run in CI/CD for free-threading builds only
if __name__ == "__main__":
    test_freethreading_basic()
```

## Migration Guidelines

### 1. Assess Your Codebase

```bash
# Identify threading usage
grep -r "threading\|Thread\|Lock\|RLock" src/ --include="*.py"

# Look for potential thread safety issues
grep -r "global\s*\|\[\s*\|{\s*\|=" src/ --include="*.py" | grep -v "def \|class \|import"
```

### 2. Dependency Audit

```bash
# Generate requirements freeze
pip freeze > requirements.txt

# Check each package (manual process initially)
# Eventually use automated tools as they become available
```

### 3. Phased Rollout

1. **Development**: Start using free-threading builds in development
2. **Testing**: Run test suite in free-threading environment
3. **Staging**: Deploy to staging with free-threading builds
4. **Production**: Monitor performance and stability before full rollout

### 4. Monitoring in Production

```python
# Add metrics to monitor threading behavior
import threading
import time
from collections import defaultdict

thread_metrics = defaultdict(int)
thread_metrics_lock = threading.Lock()

def instrumented_worker(worker_id):
    start_time = time.time()
    try:
        # Your work here
        result = do_work()
    finally:
        elapsed = time.time() - start_time
        with thread_metrics_lock:
            thread_metrics[f"worker_{worker_id}_count"] += 1
            thread_metrics[f"worker_{worker_id}_time"] += elapsed

# Periodically report metrics
def report_thread_metrics():
    with thread_metrics_lock:
        metrics = dict(thread_metrics)
        thread_metrics.clear()
    # Send to your monitoring system
    print(f"Thread metrics: {metrics}")
```

## Resources and References

- **PEP 703**: Making the Global Interpreter Lock Optional in CPython
  https://peps.python.org/pep-0703/

- **Python 3.14 Release Schedule**
  https://devguide.python.org/versions/3.14/

- **Free-threading Documentation**
  https://docs.python.org/3.14/c-api/freethreading.html

- **Community Tracking**
  https://github.com/gil-less/python/wiki

- **Compatibility Testing**
  https://freethreading.python.org/

## Troubleshooting

### Common Issues

1. **"DLL load failed" or import errors**
   - Solution: Ensure all dependencies have free-threading compatible builds
   - Try: `pip install --upgrade <package>` to get latest wheels

2. **Increased memory usage**
   - Solution: Monitor memory usage, consider reducing thread count
   - Free-threading may use slightly more memory per thread

3. **Race conditions appearing**
   - Solution: Review code for thread safety, add proper synchronization
   - Use tools like `threading.Lock`, `threading.RLock`, or `queue.Queue`

4. **Performance degradation**
   - Solution: Profile your specific workload
   - Some workloads may be better suited to ProcessPoolExecutor or asyncio

### Debugging Tips

```python
# Enable free-threading debug info (if available)
import sys
if hasattr(sys, '_freethreading_debug'):
    sys._freethreading_debug = True

# Use faulthandler for crash diagnostics
import faulthandler
faulthandler.enable()

# Simple deadlock detection
import threading
timeout = 30.0  # seconds

def safe_lock(lock):
    """Acquire lock with timeout to prevent deadlocks."""
    acquired = lock.acquire(timeout=timeout)
    if not acquired:
        raise TimeoutError(f"Could not acquire lock {lock} within {timeout}s")
    try:
        yield
    finally:
        lock.release()
```
