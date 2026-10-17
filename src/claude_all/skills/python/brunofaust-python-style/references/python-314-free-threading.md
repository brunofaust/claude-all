# Python 3.14 Free-Threading Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

Python 3.14 introduces free-threaded builds (PEP 703) that make the Global Interpreter Lock (GIL) optional. Consider using free-threading when:

- You have CPU-bound Python workloads that could benefit from true parallelism
- Your application spends significant time in pure Python code (not waiting for I/O or C extensions)
- You're deploying to environments where you can control the Python runtime (containers, managed services)
- Your dependencies are compatible with free-threaded builds (most pure Python packages work, C extensions may need updates)

**Not recommended for:**
- Applications primarily limited by I/O, network, or database operations
- Environments where you cannot control the Python runtime version
- Applications with many C extension dependencies that haven't been updated for free-threading

## Pros and Cons

### Pros

**Performance Benefits:**
- True parallel execution of Python threads (no GIL contention)
- Better utilization of multi-core CPUs for Python workloads
- Can achieve near-linear scaling for CPU-bound pure Python tasks
- Lower memory overhead compared to multiprocessing for shared data scenarios

**Development Benefits:**
- Simpler threading model compared to multiprocessing
- Shared memory space makes data sharing easier than with processes
- Compatible with existing threading code (when dependencies support it)
- No need to serialize/deserialize data between processes

### Cons

**Compatibility Risks:**
- C extensions must be updated to work with free-threading (many popular ones still need updates)
- Potential for race conditions in code that previously relied on GIL for thread safety
- Some debugging tools may not fully support free-threaded builds yet
- Third-party package compatibility varies

**Operational Considerations:**
- Requires Python 3.14+ (may not be available in all environments yet)
- Free-threaded builds may have slightly higher memory overhead per thread
- Need to audit dependencies for free-threading compatibility
- May need to add explicit locking where GIL previously provided implicit safety

## How to Implement

### Building/Installing Free-Threaded Python

To use free-threading, you need a free-threaded Python 3.14+ build:

```bash
# Using uv (recommended)
uv python install 3.14 --free-threaded

# Or compile from source
./configure --enable-free-threading
make -j$(nproc)
make install
```

### Checking if You're Running Free-Threaded

```python
import sys
import threading

def is_freethreaded():
    """Check if running in free-threaded mode."""
    return hasattr(sys, 'getfreecount') or (
        hasattr(threading, 'get_counters') and 
        threading.get_counters() is not None
    )

# Alternative check
import _thread
is_freethreaded = hasattr(_thread, 'getfreecount')
```

### Writing Thread-Safe Code

With free-threading enabled, the GIL no longer protects shared data access:

```python
# OLD: GIL provided implicit safety for simple operations (not reliable to depend on!)
counter = 0
def increment():
    global counter
    counter += 1  # NOT thread-safe even with GIL!

# NEW: Explicit synchronization required
import threading

counter = 0
counter_lock = threading.Lock()

def increment():
    global counter
    with counter_lock:
        counter += 1  # Now thread-safe
```

### Using ThreadPoolExecutor with Free-Threading

```python
from concurrent.futures import ThreadPoolExecutor
import threading

# Shared resource requiring protection
shared_data = {}
data_lock = threading.Lock()

def worker(item):
    # Do CPU-bound work
    result = expensive_computation(item)
    
    # Safely update shared state
    with data_lock:
        shared_data[item] = result
    
    return result

# Usage
with ThreadPoolExecutor(max_workers=8) as executor:
    futures = [executor.submit(worker, item) for item in work_items]
    results = [f.result() for f in futures]
```

### InterpreterPoolExecutor Alternative

For CPU-bound pure Python work that doesn't need shared state:

```python
from concurrent.futures import InterpreterPoolExecutor

def pure_python_computation(data):
    # This runs in true parallelism (no GIL)
    return sum(x * x for x in data)

# Better for pure Python CPU work with no shared mutable state
with InterpreterPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(pure_python_computation, data_chunks))
```

## How to Check Dependencies Compatibility

### Checking Individual Packages

1. **Look for free-threading support indicators:**
   - Package documentation mentioning Python 3.14 or free-threading support
   - PyPI classifiers: `Programming Language :: Python :: 3.14` + `Free Threading`
   - Release notes mentioning free-threading or PEP 703 compatibility

2. **Test with free-threaded Python:**
   ```bash
   # Create isolated test environment
   uv venv --python 3.14-free-threaded .venv-ft
   source .venv-ft/bin/activate
   
   # Install your dependencies
   uv pip install -r requirements.txt
   
   # Run your test suite
   uv run pytest
   ```

3. **Check for known problematic packages:**
   Some packages that may need updates:
   - Old versions of NumPy, Pandas, SciPy (check for 3.14-compatible builds)
   - Cython extensions (need regeneration with free-threading support)
   - Custom C extensions in your codebase
   - Debugging/profiling tools (some may need updates)

### Automated Compatibility Checking

Add this to your CI pipeline to test free-threading compatibility:

```yaml
# .github/workflows/free-threading-check.yml
name: Free-Threading Compatibility

on:
  push:
    branches: [ main ]
  pull_request:

jobs:
  free-threading-test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    
    - name: Setup free-threaded Python
      uses: astral-sh/setup-uv@v2
      with:
        python-version: "3.14-free-threaded"
    
    - name: Install dependencies
      run: uv pip install -e ".[dev]"
    
    - name: Run tests
      run: uv run pytest
```

### Dependency Analysis Tools

Use `pipdeptree` or similar to analyze your dependency tree:

```bash
# In free-threaded environment
uv pip install pipdeptree
uv pip list --format=freeze > requirements.txt
pipdeptree --freeze requirements.txt
```

Look for packages with known issues or missing free-threading support.

### Handling Incompatible Dependencies

1. **Check for updates:** Many popular packages are adding free-threading support
2. **Use conditional dependencies:** 
   ```toml
   # pyproject.toml
   [project.optional-dependencies]
   freethreading = [
       "package-name>=2.0.0",  # version with free-threading support
   ]
   ```
3. **Isolate incompatible code:** Run incompatible C extensions in separate processes
4. **Consider alternatives:** Look for pure Python alternatives or different libraries

## Best Practices

### Gradual Migration Strategy

1. **Start with testing:** Run your test suite with free-threaded Python
2. **Identify threading code:** Audit your codebase for threading usage
3. **Check dependencies:** Verify critical packages work with free-threading
4. **Enable incrementally:** Consider feature flags for free-threading features
5. **Monitor performance:** Measure actual gains in your workload patterns

### Code Patterns to Review

Look for these patterns that may need attention:

```python
# Patterns that assumed GIL protection (may need explicit locks)
shared_dict[key] = value
shared_list.append(item)
counter += 1

# Patterns that are likely safe:
local_variable = compute_something()
result = expensive_function(data)  # If no shared state access
```

### Performance Testing

When benchmarking free-threading vs. traditional builds:

```python
import time
import threading
from concurrent.futures import ThreadPoolExecutor

def cpu_bound_work(n):
    # CPU-intensive pure Python work
    return sum(i * i for i in range(n))

def benchmark():
    start = time.time()
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(cpu_bound_work, 100000) for _ in range(8)]
        results = [f.result() for f in futures]
    end = time.time()
    return end - start

# Compare times between free-threaded and regular builds
```

## References

- PEP 703 -- Making the Global Interpreter Lock Optional in CPython: https://peps.python.org/pep-0703/
- Python 3.14 Release Schedule: https://devguide.python.org/versions/3.14/
- Free-threading documentation: https://docs.python.org/3.14/c-api/init.html#free-threading-support