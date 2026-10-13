# Python 3.14 Free-Threading — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces optional free-threaded builds (PEP 703) where the Global Interpreter Lock (GIL) is disabled, allowing true parallelism in Python code. This is distinct from the existing `InterpreterPoolExecutor` (PEP 734) which uses subinterpreters for isolation. Free-threading enables multiple Python threads to run concurrently on multiple CPU cores without GIL contention, while still requiring careful handling of shared mutable state.

In free-threaded mode:
- Multiple threads can execute Python bytecode in parallel
- The GIL is no longer a bottleneck for CPU-bound Python code
- Existing extension modules may need updates to be thread-safe without the GIL
- Pure Python code that previously relied on the GIL for implicit locking now requires explicit synchronization

## When to Use

Free-threading is beneficial for:
- **CPU-bound pure Python workloads** that can be parallelized across threads
- **Scenarios where subinterpreter isolation is too restrictive** (e.g., need to share complex objects between workers)
- **Gradual migration from threaded code** where you want to keep the threading model but remove GIL bottlenecks
- **Workloads that combine CPU-bound Python with I/O** where you want parallelism for the CPU portions

Avoid free-threading for:
- **I/O-bound workloads** — use `async/await` with `run_in_thread()` for blocking operations instead
- **Code that relies on GIL-implicit locking** — requires explicit synchronization which may be complex
- **Extension modules not yet updated for free-threading** — may crash or behave unpredictably
- **Situations where subinterpreters would be sufficient** — `InterpreterPoolExecutor` offers better isolation

## Pros and Cons

### Pros
- **True parallelism for CPU-bound Python**: Multiple threads can utilize multiple cores simultaneously
- **Lower overhead than processes**: Threads share memory space, reducing data serialization costs
- **Compatibility with existing threading code**: Many threaded patterns work with minimal changes
- **Fine-grained control**: Can parallelize specific sections of code rather than whole processes
- **Memory efficiency**: Shared read-only data doesn't need duplication between threads

### Cons
- **Increased complexity for shared state**: Explicit locking required for mutable shared data
- **Extension module compatibility**: Many C extensions need updates to be thread-safe without GIL
- **Debugging challenges**: Race conditions and deadlocks are more complex to diagnose
- **Not all workloads benefit**: I/O-bound tasks see little improvement
- **Potential for subtle bugs**: Assumptions about atomic operations may no longer hold

## How to Implement

### Basic Free-Threaded Execution

To leverage free-threading, ensure you're using a free-threaded Python 3.14 build (special distribution). Then use standard threading patterns with appropriate synchronization:

```python
import threading
import concurrent.futures
from typing import List

def cpu_bound_task(data_chunk: List[float]) -> float:
    """Example CPU-bound task that processes a chunk of data."""
    result = 0.0
    for value in data_chunk:
        # Simulate CPU-intensive work
        result += value ** 0.5
    return result

def process_data_parallel(data: List[List[float]], num_threads: int = None) -> List[float]:
    """Process data in parallel using free-threading."""
    if num_threads is None:
        num_threads = len(data)  # One thread per chunk

    results = [None] * len(data)
    threads = []

    def worker(chunk_idx: int, chunk: List[float]):
        results[chunk_idx] = cpu_bound_task(chunk)

    for i, chunk in enumerate(data):
        thread = threading.Thread(target=worker, args=(i, chunk))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    return results

# Example usage
if __name__ == "__main__":
    # Split data into chunks for parallel processing
    data = [[float(i) for i in range(1000)] for _ in range(10)]
    results = process_data_parallel(data)
    print(f"Results: {results}")
```

### Hybrid CPU-I/O Workloads

For workloads that combine CPU-bound Python with I/O operations, combine free-threading with async patterns:

```python
import asyncio
import threading
import aiohttp
from typing import List

async def fetch_url(session: aiohttp.ClientSession, url: str) -> str:
    """Fetch a URL asynchronously."""
    async with session.get(url) as response:
        return await response.text()

def cpu_intensive_processing(text: str) -> dict:
    """Process text content (CPU-bound)."""
    # Simulate CPU-intensive text analysis
    words = text.split()
    return {
        "word_count": len(words),
        "avg_word_length": sum(len(w) for w in words) / len(words) if words else 0,
        "unique_words": len(set(words))
    }

async def process_urls_free_threaded(urls: List[str]) -> List[dict]:
    """Process URLs: fetch (I/O) then process content (CPU) in parallel."""
    # Fetch all URLs concurrently (I/O-bound)
    async with aiohttp.ClientSession() as session:
        fetch_tasks = [fetch_url(session, url) for url in urls]
        html_contents = await asyncio.gather(*fetch_tasks)

    # Process contents in parallel using free-threading
    results = [None] * len(html_contents)
    threads = []

    def worker(idx: int, content: str):
        results[idx] = cpu_intensive_processing(content)

    for i, content in enumerate(html_contents):
        thread = threading.Thread(target=worker, args=(i, content))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    return results

# Example usage
if __name__ == "__main__":
    urls = [
        "https://httpbin.org/delay/1",
        "https://httpbin.org/delay/2",
        "https://httpbin.org/delay/1"
    ]
    # Note: This example requires a free-threaded Python 3.14 build
    results = asyncio.run(process_urls_free_threaded(urls))
    for i, result in enumerate(results):
        print(f"URL {i}: {result}")
```

### Integration with Existing Patterns

The `brunofaust-python-style` skill maintains these guidelines for free-threading:
- Use free-threading only for CPU-bound pure Python workloads
- For CPU-bound C extensions (Polars, DeltaTable), continue using `run_in_thread()`
- For I/O-bound work, use `async/await` with `run_in_thread()` for blocking operations
- Avoid mixing free-threading with asyncio in the same thread without proper isolation
- Refer to `thread_pool.py` for the single source of truth on threading mechanisms

## How to Check Dependency Compatibility

### Pure Python Modules
Most pure Python modules work in free-threaded builds but may require explicit synchronization if they:
- Use module-level mutable state
- Rely on atomic operations that are no longer atomic without the GIL
- Assume thread-safety due to the GIL's implicit locking

Check pure Python dependencies by:
1. Reviewing source code for shared mutable state at module/class level
2. Looking for assumptions about atomic operations (e.g., `list.append`, `dict assignment`)
3. Testing with concurrent access patterns in free-threaded mode

### C Extensions and Binary Dependencies
C extensions require explicit updates to be thread-safe in free-threaded mode:
- Extensions that release the GIL during long-running operations (like NumPy) may work unchanged
- Extensions that hold the GIL or access Python objects without proper locking need updates
- Extensions using static/global variables for state may cause race conditions

Check C extension dependencies by:
1. Consulting the extension's documentation for free-threading/Python 3.14 support
2. Looking for updates that mention "GIL-free" or "PEP 703" compatibility
3. Testing the extension with concurrent threads in free-threaded mode
4. Checking if the extension uses PyGILState API or proper locking mechanisms

### Internal Modules
For internal code:
1. Audit module-level variables for mutable state
2. Review any use of `threading.local()` for thread-specific state
3. Ensure proper locking (Lock, RLock, Semaphore) for shared resources
4. Consider using immutable data structures where possible
5. Refer to `enforcement.md` for banned-api rules regarding unsafe threading patterns

### Compatibility Checklist
Use this checklist when evaluating dependencies for free-threading:

| Dependency Type | Check Items | Action |
|----------------|-------------|--------|
| Pure Python | Module-level mutable state, atomic operation assumptions | Add locking or use immutable patterns |
| C Extensions | GIL usage, global/static state, thread-safety claims | Verify updates or avoid |
| Internal Modules | Shared resources, improper synchronization | Refactor to use explicit locking |
| Framework Dependencies | Async compatibility, thread-safety | Check documentation and test |

### Tools and Techniques
- **Manual testing**: Run your test suite with concurrent threads in free-threaded mode
- **Stress testing**: Use tools like `hypothesis` or custom stress tests to expose race conditions
- **Code review**: Focus on shared state and synchronization patterns
- **Documentation**: Check upstream documentation for free-threading support

### When in Doubt
If unsure about a dependency's compatibility:
1. Start with the assumption it's not compatible until proven otherwise
2. Test in isolation with concurrent access patterns
3. Consider alternatives: `InterpreterPoolExecutor` for isolation or `run_in_thread()` for GIL-releasing extensions
4. Consult the project's `thread_pool.py` for the recommended approach

## Related Documentation
- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
- Consult `SKILL.md` for high-level skill conventions and recommendations
