# Python 3.14 Free-Threading Feature

This document covers Python 3.14's free-threading feature (PEP 703), which provides an alternative execution mode without the Global Interpreter Lock (GIL). This enables true parallelism for CPU-bound Python code while maintaining compatibility with existing single-threaded code.

## Overview

### What is Free-Threading?

Python 3.14 introduces a free-threading build mode (`--disable-gil`) that removes the Global Interpreter Lock (GIL), allowing multiple Python threads to execute Python bytecode simultaneously. This is different from the traditional GIL-protected build where only one thread can execute Python bytecode at a time.

In free-threading mode:
- Multiple threads can run Python code in parallel on multi-core systems
- The GIL is replaced with finer-grained locking mechanisms
- Existing C extensions may need updates to be thread-safe
- Pure Python code generally works without modification

### Relation to InterpreterPoolExecutor

While free-threading provides thread-based parallelism, the project also supports interpreter-based parallelism via `InterpreterPoolExecutor` (PEP 734) from Python 3.12+. Key differences:

| Feature | Free-Threading (Python 3.14+) | InterpreterPoolExecutor (Python 3.12+) |
|---------|-------------------------------|----------------------------------------|
| Parallelism Unit | Threads | Subinterpreters |
| Memory Sharing | Shared heap (with fine-grained locks) | Separate heaps (no sharing) |
| Communication | Shared objects (with synchronization) | Object passing (pickle-like) |
| Overhead | Lower (no interpreter creation) | Higher (interpreter creation) |
| Best For | CPU-bound tasks with shared state | Embarrassingly parallel tasks |
| Compatibility | Requires free-threading build | Works in standard builds |
| GIL Status | No GIL | GIL per interpreter |

The project provides both mechanisms:
- `InterpreterPoolExecutor`: For true isolation and avoiding shared state issues
- Free-threading: For lower-overhead parallelism when shared state is managed properly

## Use Cases

Free-threading is most beneficial for:

### CPU-Bound Pure Python Workloads
- Mathematical computations, simulations, data processing
- Algorithms that can be parallelized across CPU cores
- Workloads where threads spend most time executing Python bytecode

### Hybrid CPU/I/O Workloads
- Applications with both computational phases and I/O phases
- When computational phases can benefit from parallelism
- When I/O phases still benefit from async concurrency

### When to Choose Free-Threading Over Alternatives

| Scenario | Recommended Approach |
|----------|---------------------|
| CPU-bound pure Python | Free-threading threads or `InterpreterPoolExecutor` |
| CPU-bound with shared state | Free-threading (with proper synchronization) |
| Embarrassingly parallel, no sharing | `InterpreterPoolExecutor` |
| Blocking I/O/C extensions | `run_in_thread()` (thread pool) |
| Async-I/O bound work | Native async/await |
| Mixed CPU/I/O | Hybrid approach (see Implementation) |

## Pros and Cons

### Advantages
- **True Parallelism**: Multiple CPU cores can execute Python bytecode simultaneously
- **Lower Overhead**: No interpreter creation/destruction compared to subinterpreters
- **Shared Memory**: Easy sharing of data structures between threads (with synchronization)
- **Compatibility**: Most pure Python code works unchanged
- **Gradual Adoption**: Can enable per-module or per-function basis

### Limitations
- **Shared State Complexity**: Requires careful synchronization to avoid race conditions
- **C Extension Compatibility**: C extensions must be thread-safe or hold the GIL
- **Memory Usage**: Shared heap can lead to false sharing and cache contention
- **Debugging Difficulty**: Race conditions are non-deterministic and harder to reproduce
- **Build Requirement**: Requires Python built with `--disable-gil` flag

### Comparison with Alternatives

| Approach | Pros | Cons | Best For |
|----------|------|------|----------|
| **Free-Threading** | Lower overhead, shared memory | Synchronization complexity, C extension issues | CPU-bound Python with managed sharing |
| **InterpreterPoolExecutor** | True isolation, no sharing | Higher overhead, pickle constraints | Embarrassingly parallel, no sharing |
| **run_in_thread()** | Handles blocking C extensions/I/O | Thread pool overhead, GIL still limits Python parallelism | Blocking I/O, C extensions |
| **Native Async** | Excellent for I/O, structured concurrency | No CPU parallelism | I/O-bound async work |

## Implementation

### Basic Usage

Free-threading works with standard Python threading mechanisms when running a free-threading Python build:

```python
import threading
from concurrent.futures import ThreadPoolExecutor
import time

def cpu_bound_task(n):
    """CPU-intensive computation that benefits from free-threading."""
    result = 0
    for i in range(n):
        result += i * i
    return result

def parallel_computation():
    """Example of CPU-bound parallelization with free-threading."""
    # With free-threading Python build, this uses multiple cores
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(cpu_bound_task, 10_000_000)
            for _ in range(4)
        ]
        results = [f.result() for f in futures]

    return sum(results)

# Usage:
#   python3.14t -m myapp  # 't' suffix indicates free-threading build
#   result = parallel_computation()
```

### Hybrid CPU + I/O Workloads

For applications with both computational and I/O phases, combine free-threading with async:

```python
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
import aiohttp

async def fetch_data(session, url):
    """I/O-bound operation - stays async."""
    async with session.get(url) as response:
        return await response.text()

def process_data(data):
    """CPU-bound operation - benefits from free-threading."""
    # Simulate CPU-intensive processing
    result = sum(len(line) for line in data.split('\n'))
    return result * 2

async def hybrid_workflow():
    """Combines I/O (async) with CPU (free-threading) operations."""
    # Phase 1: Fetch data concurrently (I/O-bound)
    async with aiohttp.ClientSession() as session:
        urls = [f"https://api.example.com/data/{i}" for i in range(10)]
        raw_data_list = await asyncio.gather(
            *[fetch_data(session, url) for url in urls]
        )

    # Phase 2: Process data in parallel (CPU-bound)
    with ThreadPoolExecutor(max_workers=4) as executor:
        processed_list = list(executor.map(process_data, raw_data_list))

    # Phase 3: Save results (could be I/O or CPU)
    return sum(processed_list)

# Usage:
#   python3.14t -m myapp
#   result = asyncio.run(hybrid_workflow())
```

### Synchronization Primitives

When sharing state between threads, use appropriate synchronization:

```python
import threading
from concurrent.futures import ThreadPoolExecutor

class Counter:
    """Thread-safe counter using a lock."""
    def __init__(self):
        self._value = 0
        self._lock = threading.Lock()

    def increment(self):
        with self._lock:
            self._value += 1
            return self._value

    @property
    def value(self):
        with self._lock:
            return self._value

def worker(counter):
    """Worker function that increments shared counter."""
    for _ in range(1000):
        counter.increment()

def synchronized_example():
    """Example showing proper synchronization."""
    counter = Counter()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(worker, counter)
            for _ in range(4)
        ]
        # Wait for all to complete
        for f in futures:
            f.result()

    assert counter.value == 4000
    return counter.value
```

### Using with Project Patterns

Align with existing project concurrency patterns:

```python
# Instead of banned asyncio.to_thread or raw ThreadPoolExecutor
from src.claude_all.hooks.python-thread-subprocess-guard import run_in_thread

# For CPU-bound work in free-threading build
def cpu_intensive_operation(data):
    # Process data - benefits from multiple cores in free-threading build
    return sum(x * x for x in data)

async def process_batch_async(items):
    """Process a batch of items using free-threading for CPU work."""
    # Offload CPU-bound work to thread pool (uses free-threading if available)
    loop = asyncio.get_event_loop()

    # Process chunks in parallel
    chunk_size = len(items) // 4
    chunks = [items[i:i+chunk_size] for i in range(0, len(items), chunk_size)]

    tasks = [
        loop.run_in_executor(None, cpu_intensive_operation, chunk)
        for chunk in chunks
    ]

    results = await asyncio.gather(*tasks)
    return sum(results)
```

## Compatibility

### Dependency Compatibility Checks

When using free-threading, verify that your dependencies are compatible:

#### 1. Pure Python Dependencies
- Most pure Python packages work unchanged
- Check for any global state that might cause race conditions
- Verify no reliance on GIL-specific behavior

#### 2. C Extension Dependencies
Critical check: Does the extension release the GIL during long operations?

**Safe Patterns** (can use free-threading):
- Extensions that release GIL during computation (e.g., NumPy, SciPy)
- Extensions designed for multi-threaded use
- Extensions using proper locking for shared state

**Unsafe Patterns** (require `run_in_thread` instead):
- Extensions that hold GIL for long periods
- Extensions with internal global state not protected by locks
- Extensions not designed for concurrent use

#### 3. Thread Safety Checklist
For each dependency, verify:
- [ ] No unsafe global mutable state
- [ ] Proper locking for shared resources
- [ ] GIL released during blocking operations (for C extensions)
- [ ] Reentrant/thread-safe API
- [ ] No reliance on thread-specific storage assumptions

### Strategies for Handling Incompatibilities

#### 1. Selective Offloading
Use free-threading for compatible workloads, fall back to alternatives for incompatible ones:

```python
import sys
from concurrent.futures import ThreadPoolExecutor
from src.claude_all.hooks.python-thread-subprocess-guard import run_in_thread

def is_freethreading_supported():
    """Check if running in free-threading Python build."""
    # In free-threading build, sys.flags indicates GIL status
    return hasattr(sys, 'flags') and not getattr(sys.flags, 'gil', True)

def process_data_safe(data):
    """Process data using appropriate method based on compatibility."""
    if is_freethreading_supported():
        # Use free-threading for CPU-bound work
        return cpu_intensive_operation(data)
    else:
        # Fall back to thread pool for blocking work
        return run_in_thread(cpu_intensive_operation, data)
```

#### 2. Module-Level Adaptation
Adapt at the module level based on Python build:

```python
# mymodule/processor.py
import sys

if hasattr(sys, 'flags') and not getattr(sys.flags, 'gil', True):
    # Free-threading build - use threading directly
    from concurrent.futures import ThreadPoolExecutor
    def parallel_process(data):
        with ThreadPoolExecutor() as executor:
            return list(executor.map(process_item, data))
else:
    # Standard build - use InterpreterPoolExecutor or run_in_thread
    from src.claude_all.skills.python.brunofaust-python_style.references.async_patterns import InterpreterPoolExecutor
    def parallel_process(data):
        with InterpreterPoolExecutor() as executor:
            return list(executor.map(process_item, data))
```

#### 3. Dependency Isolation
Isolate incompatible dependencies in separate processes or threads:

```python
from src.claude_all.hooks.python-thread-subprocess-guard import run_in_thread, run_exec

def process_with_incompatible_lib(data):
    """Handle incompatible C extension by offloading to thread."""
    # This runs in a thread pool, suitable for C extensions that don't release GIL
    return run_in_thread(incompatible_c_extension_func, data)

def process_with_isolated_lib(data):
    """Handle problematic library by isolating in subprocess."""
    # For truly incompatible cases, use subprocess isolation
    return run_exec("python", "-c",
                   f"import sys; sys.path.append('.'); "
                   f"from mymodule import process; print(process({data}))")
```

### Project-Specific Guidelines

Following the patterns established in `async-patterns.md` and enforcement rules:

#### When to Use Free-Threading
- ✅ CPU-bound pure Python tasks in free-threading builds
- ✅ Workloads where shared state can be properly synchronized
- ✅ Hybrid applications separating CPU (free-threading) and I/O (async) phases

#### When to Avoid Free-Threading
- ❌ When using incompatible C extensions (use `run_in_thread` instead)
- ❌ When true isolation is needed (use `InterpreterPoolExecutor` instead)
- ❌ For I/O-bound work (use native async instead)
- ❌ When debugging complex race conditions (consider simpler approaches first)

#### Project Concurrency Rules
1. **No raw `asyncio.to_thread`** → Use `run_in_thread()` (enforced by ruff)
2. **No raw `ThreadPoolExecutor`** → Use `run_in_thread()` for consistency
3. **Prefer `InterpreterPoolExecutor`** for CPU-bound pure Python when isolation is needed
4. **Consider free-threading** for CPU-bound pure Python when lower overhead is desired and sharing is manageable
5. **Always use `run_in_thread()`** for blocking I/O and C extensions

## Related References

- [`async-patterns.md`](async-patterns.md): Detailed comparison of `InterpreterPoolExecutor` vs `run_in_thread()`
- [`enforcement.md`](enforcement.md): Concurrency-related banned APIs and project rules
- [`threading` documentation](https://docs.python.org/3/library/threading.html): Standard library threading module
- [PEP 703](https://peps.python.org/pep-0703/): Making CPython the Global Interpreter Lock Optional
- [PEP 734](https://peps.python.org/pep-0734/): Allowing Extension Modules to Initialize Multiple Interpreter States

## Further Reading

For more information on Python free-threading:
- Official Python documentation: [What's New in Python 3.14](https://docs.python.org/3/whatsnew/3.14.html#gil)
- PEP 703 rationale and implementation details
- Performance benchmarks and case studies
- Community discussions and adoption guides
