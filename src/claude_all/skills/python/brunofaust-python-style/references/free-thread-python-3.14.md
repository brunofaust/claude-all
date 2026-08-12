# Free-Thread in Python 3.14

## What is Free-Thread?

Free-thread execution in Python 3.14 allows for true parallelism by utilizing multiple interpreters, bypassing the Global Interpreter Lock (GIL) for CPU-bound workloads. This is achieved through the `concurrent.futures.InterpreterPoolExecutor`, which manages sub-interpreters, each with its own GIL.

## When to Use

Use free-thread execution for:
- **CPU-bound tasks**: Heavy computations, data processing, or number crunching that doesn't release the GIL.
- **Parallelism**: When you need to execute multiple CPU-bound tasks concurrently to speed up overall processing time.

## Pros and Cons

### Pros
- **True Parallelism**: Execute CPU-bound tasks in parallel using multiple sub-interpreters.
- **Lower Overhead**: Compared to `ProcessPoolExecutor`, `InterpreterPoolExecutor` has lower overhead for CPU-bound tasks.

### Cons
- **Shared State Challenges**: Sub-interpreters have isolated memory spaces; sharing mutable state between them requires synchronization.
- **Pickling Requirements**: Tasks and results must be picklable to be executed across sub-interpreters.

## Implementation

### Basic Usage
```python
from concurrent.futures import InterpreterPoolExecutor

def compute_square(x: int) -> int:
    """CPU-bound computation."""
    return x * x

# Similar API to ThreadPoolExecutor / ProcessPoolExecutor
with InterpreterPoolExecutor() as executor:
    results = list(executor.map(compute_square, range(100)))
```

### Advanced: Mixed Workloads
For workloads that combine CPU-bound and I/O-bound tasks, use a hybrid approach:
```python
import asyncio
from concurrent.futures import InterpreterPoolExecutor

async def process_items(items: list[int]) -> None:
    """Process CPU-bound tasks in parallel and handle I/O."""
    loop = asyncio.get_running_loop()

    # Offload CPU-bound work to InterpreterPoolExecutor
    with InterpreterPoolExecutor() as executor:
        futures = [loop.run_in_executor(executor, compute_square, item) for item in items]
        results = await asyncio.gather(*futures)

    # Handle I/O-bound work (e.g., API calls, DB writes)
    await save_results(results)
```

## Dependency Compatibility

### Checking Compatibility
Ensure dependencies are compatible with free-thread execution:
1. **Check for GIL Releases**: Libraries that release the GIL (e.g., NumPy operations) can be used within `InterpreterPoolExecutor`.
2. **Avoid Shared State**: Dependencies should not rely on shared mutable state across sub-interpreters.
3. **Pickling**: All data passed to/from the executor must be picklable.

### Handling Incompatible Dependencies
For dependencies not compatible with free-thread execution:
- Use `run_in_thread` for blocking or shared-state operations.
- Isolate incompatible code in separate modules and execute them outside the free-thread context.

## Limitations and Considerations

- **Isolated Memory**: Sub-interpreters have separate memory spaces; data sharing requires copying or synchronization mechanisms.
- **Debugging Complexity**: issues may arise from concurrent execution and state isolation.
- **Resource Management**: Overuse can lead to excessive memory consumption; monitor and adjust pool sizes as needed.

## Conclusion
Free-thread execution in Python 3.14 offers significant performance benefits for CPU-bound workloads but requires careful consideration of shared state and dependency compatibility. Use it judiciously alongside other concurrency tools like `asyncio` for I/O-bound tasks.
