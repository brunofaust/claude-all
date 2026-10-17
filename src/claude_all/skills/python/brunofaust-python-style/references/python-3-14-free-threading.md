# Python 3.14 Free-Threading — when to use, pros/cons, implementation, dependency compatibility

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

- **CPU-bound Python workloads** that can benefit from true parallelism
- **Applications currently limited by the GIL** where threads are blocked on CPU work
- **Scientific computing, data processing, or simulation workloads** with parallelizable patterns
- **When migrating from multiprocessing to threading** to reduce complexity and memory overhead
- **New projects targeting Python 3.14+** where you want to leverage modern concurrency features

**Do NOT use free-threading when:**
- Your workload is primarily I/O-bound (asyncio is already optimal)
- You have dependencies that are not free-threading compatible
- You need to support Python versions < 3.14
- Your code relies on thread-safety bugs that were masked by the GIL

## Core Concepts

### What is Free-Threading?

Python 3.14 introduces an optional **free-threaded build** (PEP 703) that removes the Global Interpreter Lock (GIL), allowing multiple threads to execute Python bytecode concurrently. This is enabled via the `--disable-gil` build flag.

### Key Differences from Traditional Python

| Aspect | Traditional Python (with GIL) | Free-Threaded Python (no GIL) |
|--------|-------------------------------|-------------------------------|
| Thread execution | Only one thread runs Python bytecode at a time | Multiple threads can run Python bytecode concurrently |
| CPU-bound threads | Serialized due to GIL contention | Can run in parallel on multiple cores |
| I/O-bound threads | Can yield GIL during I/O waits | Same behavior, but with lower overhead |
| Extension modules | Must be thread-safe or hold GIL | Must be explicitly thread-safe |
| Existing C extensions | Usually work (may need GIL management) | Require updating for thread safety |

### How Free-Threading Works

1. **Interpreter level**: The GIL is removed from the core interpreter loop
2. **Reference counting**: Uses atomic operations for refcount updates
3. **Memory allocation**: Employs thread-safe memory allocators
4. **Object internals**: Certain objects (like dict, list) get fine-grained locking or become thread-local
5. **Extension modules**: Must opt-in to thread safety using new APIs

## Best Practices Summary

### When to Enable Free-Threading

1. **Benchmark first**: Measure your workload with and without the GIL
2. **Check dependencies**: Verify all C extensions and libraries are compatible
3. **Start with new code**: Begin new projects in free-threading mode
4. **Gradual migration**: Move existing code incrementally, testing thoroughly
5. **Monitor for issues**: Watch for race conditions, crashes, or performance regressions

### Implementation Guidelines

#### 1. Building/Installing Free-Threaded Python

```bash
# Download Python 3.14 source
wget https://www.python.org/ftp/python/3.14.0/Python-3.14.0.tgz
tar -xzf Python-3.14.0.tgz
cd Python-3.14.0

# Configure with free-threading disabled
./configure --disable-gil --enable-optimizations
make -j$(nproc)
sudo make install

# Verify installation
python3.14 -c "import sys; print('_gildisabled' in sys._config_vars)"
# Should print True if free-threading is enabled
```

#### 2. Using Free-Threading in Code

```python
import threading
import time
import sys

def cpu_bound_work(n):
    """CPU-intensive function that benefits from free-threading"""
    total = 0
    for i in range(n):
        total += i * i
    return total

def worker(work_id, n, results):
    """Worker function for threading"""
    result = cpu_bound_work(n)
    results[work_id] = result
    print(f"Worker {work_id} completed")

# Check if running in free-threading mode
if '_gildisabled' in sys._config_vars:
    print("Running in free-threading mode")
else:
    print("Running with GIL - consider free-threading build for CPU work")

# Example usage
if __name__ == "__main__":
    n_workers = 4
    work_size = 10_000_000
    results = [0] * n_workers
    threads = []

    start_time = time.time()

    for i in range(n_workers):
        thread = threading.Thread(target=worker, args=(i, work_size, results))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    end_time = time.time()
    print(f"Total time: {end_time - start_time:.2f}s")
    print(f"Results: {results}")
```

#### 3. Thread-Safe Programming Practices

```python
# Use threading.Lock for shared mutable state
import threading

class Counter:
    def __init__(self):
        self._value = 0
        self._lock = threading.Lock()

    def increment(self):
        with self._lock:
            self._value += 1

    @property
    def value(self):
        with self._lock:
            return self._value

# Prefer immutable data structures when possible
from threading import local

# Thread-local storage for per-thread state
thread_local_data = local()

def process_item(item):
    # Each thread gets its own storage
    if not hasattr(thread_local_data, 'counter'):
        thread_local_data.counter = 0
    thread_local_data.counter += 1
    return thread_local_data.counter
```

### Dependency Compatibility Checking

#### 1. Runtime Check

```python
import sys
import threading

def check_free_threading_support():
    """Check if current Python build supports free-threading"""
    is_free_threaded = '_gildisabled' in sys._config_vars
    print(f"Free-threading enabled: {is_free_threaded}")

    # Check threading module capabilities
    if hasattr(threading, 'get_lock_info'):
        lock_info = threading.get_lock_info()
        print(f"Threading lock info: {lock_info}")

    return is_free_threaded

# Usage
if check_free_threading_support():
    print("Safe to use free-threading features")
else:
    print("Falling back to GIL-limited threading")
```

#### 2. Library Compatibility Verification

```python
# Check key libraries for free-threading compatibility
def check_dependency_compatibility():
    """Verify common dependencies work with free-threading"""
    dependencies = [
        ('numpy', 'np'),
        ('pandas', 'pd'),
        ('orjson', None),
        ('xxhash', None),
        ('uvloop', None),
        ('aiobotocore', None),
        ('cachebox', None),
        ('polars', None),
        ('pydantic', None),
        ('structlog', None)
    ]

    results = {}
    for dep_name, import_alias in dependencies:
        try:
            if import_alias:
                module = __import__(import_alias)
            else:
                module = __import__(dep_name)

            # Basic functionality test
            results[dep_name] = {
                'available': True,
                'version': getattr(module, '__version__', 'unknown'),
                'free_threading_safe': 'unknown'  # Would need specific tests
            }
            print(f"✓ {dep_name} imported successfully")
        except ImportError as e:
            results[dep_name] = {
                'available': False,
                'error': str(e)
            }
            print(f"✗ {dep_name} import failed: {e}")
        except Exception as e:
            results[dep_name] = {
                'available': True,
                'error': str(e)
            }
            print(f"⚠ {dep_name} imported but error: {e}")

    return results

# Run compatibility check
# compatibility_results = check_dependency_compatibility()
```

#### 3. Common Issues and Solutions

**Problem**: Extension modules crash or behave unpredictably
**Solution**:
- Check if the extension has been updated for free-threading
- Look for `--disable-gil` or free-threading support in documentation
- Consider using process-based parallelism (multiprocessing) as fallback
- Report issues to library maintainers

**Problem**: Performance worse than GIL version
**Solution**:
- Ensure workload is truly CPU-bound (not I/O bound)
- Check for excessive locking contention in your code
- Verify proper use of thread-local storage
- Consider that some workloads may not scale linearly due to memory bandwidth limits

**Problem**: Race conditions appearing
**Solution**:
- Audit all shared mutable state
- Use appropriate locking mechanisms (threading.Lock, RLock, etc.)
- Consider using queue.Queue for thread communication
- Use threading.local for per-thread state when appropriate

## Migration Strategy

### 1. Assessment Phase
```bash
# Check current Python version
python3 --version

# Test for free-threading availability
python3 -c "import sys; print('_gildisabled' in sys._config_vars)"

# Profile current workload to identify bottlenecks
python3 -m cProfile -s cumulative your_script.py
```

### 2. Dependency Verification
```bash
# Create requirements check script
cat > check_deps.py << 'EOF'
import subprocess
import sys
import json

def get_installed_packages():
    result = subprocess.run([sys.executable, '-m', 'pip', 'list', '--format=json'],
                          capture_output=True, text=True)
    return json.loads(result.stdout)

def check_package(package_name):
    try:
        __import__(package_name)
        return True
    except ImportError:
        return False

packages = get_installed_packages()
print("Checking common packages for free-threading readiness...")
for pkg in packages:
    name = pkg['name'].lower()
    if name in ['numpy', 'pandas', 'orjson', 'xxhash', 'uvloop',
                'aiobotocore', 'cachebox', 'polars', 'pydantic', 'structlog']:
        status = "✓" if check_package(name) else "✗"
        print(f"{status} {name} {pkg['version']}")
EOF

python3 check_deps.py
```

### 3. Testing Strategy
1. **Unit tests**: Run existing test suite to catch regressions
2. **Stress tests**: Create concurrent workloads to surface race conditions
3. **Performance benchmarks**: Compare throughput with/without free-threading
4. **Memory usage**: Monitor for increases due to thread-safe structures
5. **Extension testing**: Pay special attention to any C extensions used

### 4. Deployment Considerations
- **Container images**: Build separate images for free-threading vs GIL versions
- **Feature flags**: Use environment variables to enable/disable free-threading features
- **Monitoring**: Add metrics to track threading performance and error rates
- **Fallbacks**: Implement graceful degradation to GIL mode if needed

## Resources

- **PEP 703**: https://peps.python.org/pep-0703/
- **Python 3.14 Documentation**: https://docs.python.org/3.14/
- **Free-threading Wiki**: https://wiki.python.org/moin/Gilectomy
- **Compatibility Tracking**: https://github.com/python/cpython/issues/104324
