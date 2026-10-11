# Free-threading — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## When to Use

- **Python 3.14+** when you need true parallelism for CPU-bound Python code and can accept the trade-offs of optional GIL mode.
- **Only** when all dependencies are verified compatible with free-threading mode (see *Checking Dependency Compatibility* below).
- For **CPU-bound** pure Python workloads that would benefit from parallel execution across multiple cores.
- **Not** for I/O-bound work (use async/await with `uvloop` and `run_in_thread` for blocking I/O) or when dependencies lack free-threading support.

## Core Concepts

### What is Free-threading?

Python 3.14 introduces an optional build mode (`--disable-gil`) that replaces the Global Interpreter Lock (GIL) with finer-grained locking mechanisms, allowing multiple threads to execute Python bytecode in parallel. This is **not** the default mode; you must use a special Python interpreter built with `./configure --disable-gil`.

### Key Implications

- **Thread safety**: Extension modules and Cython code must be updated to use the new locking APIs or risk data races.
- **Performance**: Single-threaded performance may slightly decrease due to increased locking overhead; multi-threaded CPU-bound workloads can see significant speedups.
- **Compatibility**: Pure Python code is generally thread-safe with respect to the GIL removal, but C extensions must be audited.
- **Migration**: Code that previously relied on the GIL for implicit locking (e.g., assuming atomicity of `list.append()`) must now use explicit synchronization.

### How It Differs from Existing Approaches

| Approach          | Parallelism | GIL Status       | Use Case                     |
|-------------------|-------------|------------------|------------------------------|
| `asyncio`         | Concurrency | GIL held         | I/O-bound, async-friendly    |
| `threading`       | Limited     | GIL held         | I/O-bound, blocking calls    |
| `multiprocessing` | True        | No GIL per proc  | CPU-bound, high overhead     |
| **Free-threading**| **True**    | **Optional GIL** | **CPU-bound, low-overhead**  |

## Best Practices Summary

1. **Verify your Python build** is free-threading capable (`python -c "import sys; print('_gildISABLED' in sys.modules or hasattr(sys, 'gil_enabled') and not sys.gil_enabled())"`).
2. **Audit all dependencies** for free-threading compatibility using the `gil` distribution metadata or upstream documentation.
3. **Use explicit locking** (`threading.Lock`, `threading.RLock`, or `sync` module primitives) for shared mutable state.
4. **Avoid relying on GIL-induced atomicity** for operations like `list.append`, `dict.update`, or integer increments.
5. **Prefer message passing** (queues, `asyncio.Queue`) over shared memory when possible.
6. **Benchmark both modes** — free-threading may worsen single-threaded performance.
7. **Use `Py_GIL_DISABLED` macro** in C extensions to conditionally compile GIL-aware code.
8. **Monitor for new race conditions** that only manifest under parallel execution.

## Checking Dependency Compatibility

### Using Package Metadata

Packages compatible with free-threading should declare it via:

- **PyPI Trove classifier**: `Framework :: Python :: 3.14 :: Free threading`
- **Distribution metadata**: `Free-Threading: Compatible` in `METADATA` or `pyproject.toml`

### Manual Verification

1. **Check documentation**: Look for explicit free-threading/Python 3.14 support statements.
2. **Inspect wheels**: Free-threading compatible wheels are tagged with `abi3` and `platlib` but may require specific tags.
3. **Test in isolation**: Run your test suite with `PYTHON_GIL=0` environment variable (if supported by your build) to detect issues.
4. **Consult upstream**: Many popular libraries (NumPy, Pandas, etc.) have free-threading branches or tracking issues.

### Example `pyproject.toml` Check

```toml
[tool.uv]
# When using uv, you can override to free-threading builds
python = { version = "3.14", allow-prereleases = true }

[project.dependencies]
# Prefer packages with free-threading support
numpy = { version = ">=1.26.0", markers = "python_version >= '3.14'" }
```

### Runtime Check

```python
import sys
import threading

def is_freethreading_enabled():
    """Check if running in free-threading mode."""
    if hasattr(sys, "gil_enabled"):
        return not sys.gil_enabled()
    # Fallback for older checks
    import _thread
    return hasattr(_thread, "getlock") and not hasattr(_thread, "allocate_lock")

if is_freethreading_enabled():
    print("Running in free-threading mode")
else:
    print("Running with GIL enabled")
```

## When NOT to Use Free-threading

- **Dependency chain not verified**: Even one incompatible C extension can cause silent data corruption.
- **I/O-bound applications**: Async/await with `uvloop` remains more efficient.
- **Low CPU utilization**: Overhead of fine-grained locking may reduce performance.
- **Third-party plugins**: Lack of control over extension safety (e.g., user-defined functions in plugins).
- **Real-time systems**: Increased latency variance from locking overhead.

## Migration Strategy

1. **Start with a dependency audit** using `pip list --format=freeze` and cross-reference with compatibility lists.
2. **Build a free-threading Python** (see [Python 3.14 README](https://docs.python.org/3.14/using/unix.html#building-python)).
3. **Run tests in isolation** with `PYTHON_GIL=0` (if supported) or in a dedicated environment.
4. **Gradually roll out** to non-critical services before wider adoption.
5. **Monitor production metrics** for performance regressions or new error patterns.

## Related References

- [`async-patterns.md`](async-patterns.md) — For I/O-bound concurrency (the default recommendation)
- [`testing.md`](testing.md) — For strategies to detect race conditions
- [`error-handling.md`](error-handling.md) — For handling exceptions in parallel contexts
