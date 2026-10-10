# Free-threading in Python 3.14 — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

Consider free-threading (PEP 703) when you have:

- **CPU-bound pure Python workloads** that are currently limited by the Global Interpreter Lock (GIL)
- **Applications that can tolerate slight performance regression in single-threaded code** (typically 5-10% slower due to finer-grained locking)
- **Dependencies that are certified free-threading compatible** or pure Python with no reliance on GIL-sensitive C extensions
- **Workloads that benefit from true parallelism** (e.g., scientific computing, data processing, simulation) rather than I/O-bound concurrency

Do **not** use free-threading for:

- Pure I/O-bound applications (asyncio with uvloop already handles concurrency efficiently)
- Workloads relying on C extensions that release the GIL (these already achieve parallelism via threads)
- Environments where dependency compatibility cannot be verified
- Projects requiring maximum single-threaded performance

## Pros and Cons

### Pros

- **True parallelism for CPU-bound Python code**: Multiple threads can execute Python bytecode simultaneously
- **Lower overhead than multiprocessing**: Shared memory space avoids pickling/unpickling and complex IPC
- **Compatible with existing threading code**: No changes needed to standard threading models if dependencies support it
- **Gradual adoption**: Can run in legacy GIL mode if needed by setting `PYTHON_GIL=1` environment variable

### Cons

- **Performance regression in single-threaded mode**: Typically 5-10% slower due to finer-grained locking
- **Dependency compatibility requirements**: All C extensions must be free-threading compatible
- **Increased complexity in debugging**: Race conditions that were masked by the GIL may surface
- **Limited ecosystem support**: Early adoption phase; many popular libraries may not yet be compatible
- **Memory overhead**: Slightly higher memory usage per thread due to finer-grained locks

## How to Implement

### Enabling Free-threading Build

Python 3.14 provides a special free-threading build (sometimes labeled `python3.14t` or via configure flag). To use:

1. **Install the free-threading variant**:
   ```bash
   # Using uv (preferred)
   uv python install 3.14.0-t

   # Or compile from source with:
   ./configure --disable-gil
   make && make install
   ```

2. **Verify the build**:
   ```python
   import sys
   import _thread
   print(sys.version)  # Should show "free-threading" in the version string
   print(_thread.getgil())  # Should return None in free-threading build
   ```

### Writing Free-threading Compatible Code

Most existing threading code works unchanged, but follow these guidelines:

1. **Use standard threading primitives**:
   ```python
   import threading
   from concurrent.futures import ThreadPoolExecutor

   def worker(item):
       # CPU-bound pure Python work
       return complex_computation(item)

   with ThreadPoolExecutor(max_workers=4) as executor:
       results = list(executor.map(worker, data))
   ```

2. **Avoid shared mutable state without proper synchronization**:
   ```python
   # GOOD: Use locks for shared state
   counter = 0
   counter_lock = threading.Lock()

   def increment():
       nonlocal counter
       with counter_lock:
           counter += 1

   # BAD: Unprotected shared state (may cause race conditions)
   # counter += 1  # Never do this without synchronization
   ```

3. **Leverage interpreter pools for CPU-bound tasks** (PEP 734):
   ```python
   # Python 3.14+ only: True parallelism with separate interpreters
   from concurrent.futures import InterpreterPoolExecutor

   def cpu_bound_task(data):
       # Pure Python, no shared state
       return process_data(data)

   with InterpreterPoolExecutor() as executor:
       results = list(executor.map(cpu_bound_task, datasets))
   ```

4. **Continue using asyncio for I/O-bound work**:
   Free-threading does not replace asyncio for I/O concurrency. Use:
   - `asyncio` + `uvloop` for network/disk I/O
   - `run_in_thread()` for blocking CPU-bound calls (if not using InterpreterPoolExecutor)
   - Free-threading threads for CPU-bound pure Python workloads

### Project Configuration

Update your project to explicitly support free-threading:

1. **Add to `pyproject.toml`**:
   ```toml
   [tool.uv]
   python = "3.14.0-t"  # or specify free-threading variant

   [tool.uv.sources]
   # Override dependencies that need free-threading compatible versions
   ```

2. **Document the requirement**:
   ```markdown
   ## Python Version

   This project requires Python 3.14 with free-threading support (build `3.14.0-t` or equivalent).
   ```

## Checking Dependency Compatibility

### Automated Checks

1. **Use `pip` with free-threading build**:
   ```bash
   # Create a virtual environment with the free-threading Python
   uv venv --python 3.14.0-t .venv
   source .venv/bin/activate

   # Install dependencies - incompatible packages will fail to import
   pip install -e .
   ```

2. **Run your test suite**:
   ```bash
   pytest  # Any import errors or runtime issues indicate incompatibility
   ```

### Manual Verification

For each dependency:

1. **Check for explicit free-threading support**:
   - Look for documentation mentioning "free-threading", "nogil", or "PEP 703"
   - Check PyPI classifiers for `FreeThreading :: Supported`

2. **Test import and basic functionality**:
   ```python
   try:
       import dependency
       # Run a simple operation that uses the library
       result = dependency.simple_operation()
       print(f"{dependency} works in free-threading mode")
   except Exception as e:
       print(f"{dependency} incompatible: {e}")
   ```

3. **Common compatibility status** (as of Python 3.14.0 release):
   - **Likely compatible**: Pure Python packages (requests, pydantic, polars, etc.)
   - **Requires verification**: C extensions with GIL-dependent code (numpy, lxml, some cryptography libraries)
   - **Incompatible**: Libraries relying on GIL for internal correctness (rare, but check each)

### Handling Incompatible Dependencies

1. **Seek alternatives**:
   - Replace `numpy` with `array API` compatible libraries that offer free-threading builds
   - Use `polars` instead of `pandas` for dataframes (polars is pure Python/Rust and GIL-free)

2. **Isolate incompatible code**:
   ```python
   # Run incompatible sections in separate processes
   from multiprocessing import Process, Queue

   def incompatible_task(data, queue):
       # This uses a GIL-dependent C extension
       result = legacy_library.process(data)
       queue.put(result)

   # In main free-threading thread
   queue = Queue()
   process = Process(target=incompatible_task, args=(data, queue))
   process.start()
   result = queue.get()
   process.join()
   ```

3. **Contribute to upstream**:
   - Many libraries are actively working on free-threading compatibility
   - Consider sponsoring or contributing to compatibility efforts

## Best Practices

1. **Start with I/O-bound workloads**: These benefit least from free-threading but validate your setup
2. **Gradually move CPU-bound sections**: Profile to identify hotspots, then convert to free-threading threads
3. **Use InterpreterPoolExecutor for true isolation**: When sharing state is problematic
4. **Monitor performance**: Compare single-threaded (GIL enabled) vs free-threading performance
5. **Update dependencies regularly**: Compatibility improves rapidly in early adoption phases
6. **Document assumptions**: Clearly state which parts of your codebase require free-threading

## See Also

- [`async-patterns.md`](async-patterns.md) — For I/O concurrency patterns that remain essential
- [`architecture.md`](architecture.md) — For guidance on when to introduce concurrency complexity
- [type-hints.md](type-hints.md) — For PEP 695 generics useful in concurrent code
- [testing.md](testing.md) — For testing concurrent code effectively
