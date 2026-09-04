# Free-thread Python 3.14 — reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces free-threaded execution via PEP 734, which provides `InterpreterPoolExecutor` for true parallelism without the Global Interpreter Lock (GIL) limitations. Each subinterpreter has its own GIL, allowing multiple CPU-bound threads to run in parallel on multi-core systems.

Free-threaded execution differs from traditional threading approaches:
- Traditional `ThreadPoolExecutor` is limited by the GIL for CPU-bound tasks
- `InterpreterPoolExecutor` provides true parallelism by isolating state in subinterpreters
- Only picklable data can be shared between subinterpreters
- Shared mutable state across interpreters is not supported

## Use Cases

Free-threaded execution is beneficial for:

| Scenario                          | Recommended Approach         | Reason                                                                 |
|-----------------------------------|------------------------------|------------------------------------------------------------------------|
| Pure Python CPU-bound tasks       | `InterpreterPoolExecutor`    | True parallelism via subinterpreters, each with its own GIL            |
| CPU-bound C extensions            | `run_in_thread()`            | C extensions typically release the GIL during blocking operations      |
| Blocking I/O (file, network)      | `run_in_thread()`            | Simpler, lower overhead than subinterpreters                           |
| Tasks requiring shared state      | `run_in_thread()` or async   | Subinterpreters cannot share mutable state directly                    |
| Mixed CPU/I/O workloads           | Hybrid approach (see below)  | Combine executors based on workload characteristics                    |

## Pros and Cons

### Advantages
- **True parallelism**: Multiple CPU-bound threads run simultaneously on multi-core systems
- **Lower overhead**: Less resource-intensive than `ProcessPoolExecutor` (no process creation)
- **Familiar API**: Similar to `ThreadPoolExecutor` and `ProcessPoolExecutor`
- **Isolation**: Each subinterpreter has isolated state, reducing side effects

### Limitations
- **Pickling requirement**: Only picklable objects can be passed between subinterpreters
- **No shared mutable state**: Cannot directly share mutable objects between interpreters
- **Startup overhead**: Subinterpreter initialization has some cost (though less than processes)
- **Extension compatibility**: C extensions must be subinterpreter-compatible (PEP 734)

## Implementation

### Basic CPU-bound workload

For pure Python CPU-bound computations that don't require shared state:

```python
from concurrent.futures import InterpreterPoolExecutor
from typing import List


def compute_factorial(n: int) -> int:
    """CPU-intensive computation: calculate factorial."""
    if n < 0:
        raise ValueError("Factorial is not defined for negative numbers")
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result


def parallel_factorial(numbers: List[int]) -> List[int]:
    """Compute factorials in parallel using InterpreterPoolExecutor."""
    with InterpreterPoolExecutor() as executor:
        # map() preserves order of inputs
        results = list(executor.map(compute_factorial, numbers))
    return results


# Example usage
if __name__ == "__main__":
    numbers = [5, 7, 10, 12, 15]
    results = parallel_factorial(numbers)
    print(f"Factorials: {dict(zip(numbers, results))}")
```

### Hybrid CPU + I/O workload

For workloads that combine CPU-intensive processing with I/O operations:

```python
import json
from concurrent.futures import InterpreterPoolExecutor
from pathlib import Path
from typing import List, Dict


def process_file_content(content: str) -> Dict[str, int]:
    """CPU-bound: analyze text content (word frequency)."""
    words = content.lower().split()
    freq: Dict[str, int] = {}
    for word in words:
        # Simple word cleaning (remove punctuation)
        cleaned = ''.join(c for c in word if c.isalnum())
        if cleaned:
            freq[cleaned] = freq.get(cleaned, 0) + 1
    return freq


def process_file(file_path: Path) -> Dict[str, int]:
    """Handle I/O in main thread, CPU work in subinterpreters."""
    # I/O operation - better suited for run_in_thread() but shown here for completeness
    content = file_path.read_text(encoding="utf-8")
    return process_file_content(content)


def process_files_parallel(file_paths: List[Path]) -> List[Dict[str, int]]:
    """Process multiple files with hybrid approach."""
    # Use InterpreterPoolExecutor for CPU-bound text processing
    with InterpreterPoolExecutor() as executor:
        results = list(executor.map(process_file, file_paths))
    return results


# Example usage
if __name__ == "__main__":
    files = [Path("doc1.txt"), Path("doc2.txt"), Path("doc3.txt")]
    results = process_files_parallel(files)
    for i, (file_path, freq) in enumerate(zip(files, results)):
        top_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:3]
        print(f"{file_path.name}: {top_words}")
```

### Comparison with run_in_thread()

When to choose each approach:

```python
from claude_all.hooks.thread_pool import run_in_thread
from concurrent.futures import InterpreterPoolExecutor
import time


def cpu_intensive_task(n: int) -> int:
    """Pure Python CPU-bound work."""
    total = 0
    for i in range(n):
        total += i * i
    return total


def blocking_io_task() -> str:
    """Simulate blocking I/O (would be file/network in practice)."""
    time.sleep(0.1)  # Simulate I/O delay
    return "I/O completed"


def demonstrate_executors():
    """Show when to use each executor."""

    # CPU-bound pure Python -> InterpreterPoolExecutor
    with InterpreterPoolExecutor() as executor:
        cpu_results = list(executor.map(cpu_intensive_task, [100000, 200000, 150000]))

    # Blocking I/O -> run_in_thread() (more appropriate than InterpreterPoolExecutor)
    io_results = []
    for _ in range(3):
        result = run_in_thread(blocking_io_task)
        io_results.append(result)

    return cpu_results, io_results
```

## Compatibility

### Dependency Compatibility Checklist

Before using `InterpreterPoolExecutor`, verify dependencies meet these requirements:

| Check                          | How to Verify                                                                 | Alternative if Failed                     |
|--------------------------------|-------------------------------------------------------------------------------|-------------------------------------------|
| **C extension GIL release**    | Does the extension release GIL during blocking calls? (check docs/source)     | Use `run_in_thread()` instead             |
| **Picklability**               | Can objects be pickled with `pickle.dumps()`?                                | Restructure data to be picklable          |
| **Shared mutable state**       | Does the task require sharing mutable objects between workers?               | Use `run_in_thread()` or redesign         |
| **Subinterpreter compatibility**| Does C extension work with multiple subinterpreters? (PEP 734 requirement)   | Use `run_in_thread()` or isolate usage    |
| **Thread safety**              | Is the operation thread-safe when run in parallel?                           | Add synchronization or use `run_in_thread()`|

### Strategies for Handling Incompatibilities

1. **Fallback to run_in_thread()**
   ```python
   def safe_parallel_execute(func, *args, use_interpreter=True):
       """Execute with fallback based on compatibility checks."""
       if use_interpreter and is_interpreter_safe(func, args):
           with InterpreterPoolExecutor() as executor:
               return list(executor.map(func, args))
       else:
           # Fallback to thread-based execution
           from claude_all.hooks.thread_pool import run_in_thread
           return [run_in_thread(func, arg) for arg in args]
   ```

2. **Data serialization boundaries**
   ```python
   import pickle

   def prepare_for_interpreter(data):
       """Ensure data is picklable before passing to subinterpreter."""
       try:
           # Test picklability
           pickle.dumps(data)
           return data
       except (pickle.PicklingError, TypeError):
           # Convert to primitive types or raise informative error
           raise ValueError(
               f"Data of type {type(data).__name__} is not picklable "
               f"for InterpreterPoolExecutor. Consider converting to "
               f"primitive types or using run_in_thread() instead."
           )
   ```

3. **Isolated resource usage**
   - Initialize resources inside the worker function rather than sharing them
   - Use connection pools or create fresh instances per task
   - Avoid global/module-level state that isn't thread-safe

### Project-Specific Guidelines

Following the patterns established in `async-patterns.md`:

- **Prefer `InterpreterPoolExecutor`** for pure Python CPU-bound tasks (parsing, numerical computations, data transformation)
- **Use `run_in_thread()`** for:
  - Blocking I/O operations (file, network, subprocess)
  - CPU-bound C extensions that release the GIL
  - Tasks requiring shared mutable state
  - When dependencies are not subinterpreter-compatible
- **Avoid banned APIs**:
  - `asyncio.to_thread()` (use `run_in_thread()` instead)
  - Direct `ThreadPoolExecutor` or `ProcessPoolExecutor` usage
  - Raw `threading.Thread` for blocking operations

### Verification Checklist

Before deploying code using free-threaded execution:

- [ ] All arguments and return values are picklable
- [ ] No shared mutable state between workers
- [ ] C extensions are verified to work with subinterpreters (or use `run_in_thread()`)
- [ ] Error handling properly propagates exceptions from subinterpreters
- [ ] Performance testing shows benefit over sequential execution
- [ ] Resource cleanup is handled properly (no leaks in subinterpreters)

## Related Documentation

- See `async-patterns.md` for detailed comparison of execution models
- See `enforcement.md` for banned-api rules regarding threading
- See `thread_pool.py` for the project's `run_in_thread()` implementation
- Refer to PEP 734 for the full specification of subinterpreters
