# Python 3.14 Free-Threading — Reference Guide

## Overview

Python 3.14 introduces the **free-threaded build** — a CPython interpreter built with the GIL disabled (`--disable-gil`). This enables true parallel execution of pure-Python bytecode across threads while sharing the same interpreter. It complements the 3.14+ baseline's `concurrent.futures.InterpreterPoolExecutor` (PEP 734) and `run_in_thread()` conventions documented in `async-patterns.md`.

Free-threading does **not** make unsafe code safe. It removes the global interpreter lock, so data races on shared mutable state become real.

## When to Use

Use the free-threaded build when:

- **CPU-bound pure Python**: compute-heavy workloads that are not released by C extensions and need real parallelism
- **CPU-bound workload + data-parallel**: embarrassingly parallel map/reduce style work with picklable arguments/results
- **Existing thread-based code** needs more parallelism than GIL allows without rewriting with multiprocessing

### Do **NOT** use free-threading when:

- Code relies on **non-thread-safe C extensions** that assume GIL semantics for their own internal state
- Heavy **shared mutable state** without synchronization is acceptable in current codebase (free-threading exposes races)
- You are running on a platform where free-threaded CPython wheels are unavailable or untested

## Pros / Cons

| Pros | Cons |
|---|---|
| True parallelism for pure Python bytecode | Shared mutable state requires explicit synchronization |
| No process fork overhead vs `multiprocessing` | Pickling overhead for arguments/results across interpreters |
| Works with existing `threading` code after audit | Many C extensions are not free-thread compatible |
| Lower memory than processes | Debugging race conditions in shared state is harder |

## Implementation

### Interpreter Verification

Verify the running interpreter is free-threaded:

```python
import sys

if not sys.flags.freethreading:
    raise RuntimeError("Free-threading is not enabled")
```

Or via runtime check with `sysconfig`:

```python
import sysconfig
print(sysconfig.get_config_var("Py_GIL_DISABLED"))  # 1 if free-threaded
```

### Installation

Pin to a free-threaded CPython 3.14+ build. Example `pyproject.toml`:

```toml
[project]
requires-python = ">=3.14"
```

Install with `uv`:

```bash
uv pip install --python 3.14-gil-disabled mypackage
```

Refer to `references/installation.md` for build-pinning details.

### Basic Usage with `InterpreterPoolExecutor`

`concurrent.futures.InterpreterPoolExecutor` runs tasks in subinterpreters, each with its own GIL. This is the preferred parallel primitive for the 3.14+ baseline and is compatible with free-threaded builds.

```python
from concurrent.futures import InterpreterPoolExecutor

def pure_python_work(x: int) -> int:
    return sum(i*i for i in range(x))

with InterpreterPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(pure_python_work, range(10)))
```

### Hybrid Async + Free-Thread Patterns

Combine async I/O with free-threaded CPU work using the project convention `run_in_thread()` for blocking I/O and `InterpreterPoolExecutor` for CPU-bound pure Python.

```python
import asyncio
from concurrent.futures import InterpreterPoolExecutor
from myapp.core.thread_pool import run_in_thread

async def handle():
    # blocking I/O
    data = await run_in_thread(fetch_from_db)

    # CPU-bound pure Python
    with InterpreterPoolExecutor() as pool:
        results = await asyncio.get_event_loop().run_in_executor(
            pool, lambda: list(pool.map(process, data))
        )
    return results
```

The skill's guidance in `async-patterns.md` covers when to prefer `InterpreterPoolExecutor` vs `run_in_thread()` for C-extensions.

### Dependency Compatibility

Before adopting free-threading:

1. **Wheel ABI inspection**: verify wheels are built for `cp314t` (threading tag) not `cp314` (GIL). Example:
   ```bash
   pip index versions mypackage
   ```
2. **C-extension checklist**:
   - Confirm C extensions are compiled with free-thread support or provide pure-Python fallback
   - Replace or gate dependencies that use GIL-reliant APIs
3. **Runtime verification**: run `sys.flags.freethreading` check in CI and startup
4. **CI gate automation**: add a `prek.toml` check that fails if `sys.flags.freethreading` is False

## Testing and Known Limitations

- Unit tests must verify both free-threaded and GIL-enabled builds if both are supported
- Shared mutable state is a known footgun; free-threading does not make unsafe code safe
- AWS Lambda / containers may not ship free-threaded CPython by default; verify runtime

## Related Documentation

- See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
- Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
- Consult `SKILL.md` for high-level skill conventions and recommendations
