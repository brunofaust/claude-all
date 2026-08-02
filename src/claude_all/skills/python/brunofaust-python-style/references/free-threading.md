---
# Python 3.14 Free-thread Feature: `InterpreterPerSubProcess`

Python 3.14 introduces a feature called `InterpreterPerSubProcess` (PEP 703), enabling true free-threading by allowing each sub-process in a multiprocess setup to have its own Python interpreter. This improves performance and safety in concurrent applications.

## When to Use
Use this feature when working with:
- Multiprocessing with shared state
- CPU-bound tasks needing true parallelism (beyond thread pools)
- Libraries requiring per-process isolation

## Pros and Cons

### Pros
- **True parallelism**: Utilizes multiple CPU cores
- **Memory safety**: Each process has isolated memory
- **Exception isolation**: Crashes in one process don't affect others

### Cons
- **Higher memory usage**: Each process has its own interpreter
- ** IPC overhead**: Communication between processes adds latency
- **Complex state management**: Requires careful handling of shared resources

## Implementation

### Enabling Free-threading

```python
import os
import multiprocessing

# Ensure each process gets its own interpreter
if os.name == 'posix':  # Works on Unix-like systems
    mp_context = multiprocessing.get_context('spawn')
else:
    mp_context = multiprocessing.get_context('spawn')  # Fallback

def worker(num: int):
    print(f'Worker {num} running in process {os.getpid()}')

if __name__ == '__main__':
    processes = [
        mp_context.Process(target=worker, args=(i,))
        for i in range(4)
    ]
    for p in processes:
        p.start()
    for p in processes:
        p.join()
```

## Dependency Compatibility

### Checking Compatibility
1. **OS Support**: Works best on Unix-like systems (Linux/macOS)
2. **Library Support**: Ensure libraries are thread-safe if mixing with threading
3. **Dependency Versions**: Use libraries compatible with Python 3.14

### Common Pitfalls
- **Shared resources**: Avoid sharing file descriptors or sockets across processes
- **State mutation**: Use `Manager()` objects for shared state
- **Startup cost**: Process creation is more expensive than threading


## References
For deeper understanding:
- [PEP 703](https://peps.python.org/pep-0703/)
- [Python Multiprocessing Docs](https://docs.python.org/3/library/multiprocessing.html)
- `brunofaust-python-style`'s `references/async-patterns.md` for hybrid async/thread patterns
