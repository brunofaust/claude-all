# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces an official free-threaded build (PEP 703) that removes the Global Interpreter Lock (GIL) by default. The interpreter is built with `—with-freethreading` and runs with a per-interpreter state model.

Key concepts:
* **Free-threaded build**: Python interpreter compiled with the `t` ABI tag (`cp314t`). Multiple threads can execute Python bytecode concurrently.
* **GIL legacy**: Standard CPython builds retain the GIL. Free-threaded builds disable it, enabling true parallelism for CPU-bound pure-Python code.
* **InterpreterPoolExecutor**: Python 3.14 ships `concurrent.futures.InterpreterPoolExecutor` (PEP 734). It spawns multiple sub-interpreters, each with its own GIL, providing isolation for shared-state-sensitive code.
* **Compatibility**: Not all C extensions are free-thread-safe. A free-threaded interpreter can only load wheels built for the `cp314t` ABI or extensions that are explicitly GIL-agnostic.

Free-threading is orthogonal to async/await. Async is for I/O concurrency; free-threading is for CPU parallelism. The skill's default is async-first, with `run_in_thread()` for blocking I/O/C-extensions. Use free-threading only where the trade-offs are justified.

## When to Use

Use the free-threaded Python 3.14 build when **ALL** of the following hold:

* The workload is CPU-bound **pure Python** with no global mutable state.
* The code is already thread-safe and pickle-friendly.
* Dependencies are verified free-thread-compatible (see Compatibility).
* You are running on ECS/VMs, not AWS Lambda (Lambda does not ship free-threaded runtimes).
* The alternative — `InterpreterPoolExecutor` or `run_in_thread()` — is proven insufficient.

Do **NOT** use free-threading if:
* The codebase relies on global singletons, module-level caches, or non-thread-safe pure-Python libraries.
* C extensions in the dependency tree are GIL-dependent or lack `cp314t` wheels.
* You need cross-interpreter shared memory (free-threading does not provide shared state; sub-interpreters isolate state).

Typical good fits:
* CPU-bound data transformation pipelines written in pure Python with immutable parameters.
* Batch processing where tasks are independent and pickleable.
* Parallel map/reduce over CPU-bound pure-Python functions with no shared mutable state.

Typical bad fits:
* Code that uses `threading.local()`, module-level mutable globals, or libraries that mutate global registries.
* Heavy C-extension stacks (NumPy, Pandas, PyTorch, cryptography). These release the GIL already for compute but often aren't `cp314t`-compatible.
* Async applications where `run_in_thread()` + `uvloop` already saturates I/O.

## Pros and Cons

### Pros
* **True CPU parallelism** for pure Python without rewriting for multiprocessing.
* Lower process overhead than multiprocessing: threads share memory for read-only data.
* Better cache locality than process pools for read-only workloads.
* Interpreter-level isolation with `InterpreterPoolExecutor` as a middle ground.

### Cons
* **Dependency compatibility risk**: many C extensions are not yet `cp314t`-ready.
* **Shared state is unsafe**: module globals, singletons, and mutable shared objects cause race conditions unless explicitly synchronized.
* **Pickle requirement**: arguments/results passed between threads/interpreters must be pickleable. Non-pickleable objects fail at runtime.
* **Testing surface grows**: need thread-safety tests, race-condition checks, and CI gates for ABI compatibility.
* **Platform availability**: free-threaded builds are not yet standard on all platforms or package managers.
* **No Lambda support**: cannot be used in AWS Lambda runtimes today.

## Implementation

### Interpreter verification & installation

Verify you are running a free-threaded build:

```python
import sys

is_free_threaded = sys.flags.freethreading
print(f"Free-threaded: {is_free_threaded}")
# True on cp314t builds, False otherwise
```

Check ABI tag:

```python
import sysconfig
print(sysconfig.get_config_var("Py_GIL_DISABLED"))
# 1 on free-threaded builds
```

Install via `uv`:

```bash
uv python install 3.14
# Ensure the platform ships a free-threaded 3.14 build
uv pip install --python 3.14
```

`pyproject.toml` must pin the language version:

```toml
[tool.ruff]
target-version = "py314"

[tool.mypy]
python_version = "3.14"
```

### Basic free-threaded usage

With a free-threaded interpreter, the standard `ThreadPoolExecutor` can execute Python bytecode in parallel:

```python
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

def cpu_bound(x: int) -> int:
    # pure Python, no shared mutable state, pickleable
    return sum(i * i for i in range(x))

def main(items):
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(cpu_bound, items))
    return results
```

**Rule**: never share mutable state across threads. Keep functions pure, parameters immutable, return values immutable.

### Hybrid async + free-thread patterns

The skill remains async-first. Use free-threading for CPU parallelism inside async code:

```python
import asyncio
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=8)

async def process_batch(items):
    loop = asyncio.get_running_loop()
    # Offload CPU-bound pure Python to free-threaded pool
    results = await loop.run_in_executor(_executor, lambda: [cpu_bound(i) for i in items])
    return results
```

For C-extension-bound I/O, keep the existing pattern:

```python
from core.thread_pool import run_in_thread

async def io_bound():
    # run_in_thread wraps sync SDK calls; free-threading does not help here
    data = await run_in_thread(blocking_call)
```

**Decision matrix**
* I/O-bound or C-extension CPU-bound → `asyncio` + `run_in_thread()`
* CPU-bound pure Python with verified compatibility → free-threaded `ThreadPoolExecutor`
* Shared-state-sensitive CPU work → `InterpreterPoolExecutor` (sub-interpreter isolation)

### InterpreterPoolExecutor pattern

When you need isolation but want to keep free-threading benefits:

```python
from concurrent.futures import InterpreterPoolExecutor

def worker(x):
    return sum(i * i for i in range(x))

with InterpreterPoolExecutor(max_workers=4) as ex:
    results = list(ex.map(worker, items))
```

Sub-interpreters cannot share Python objects; arguments/results are pickled. This avoids GIL and shared-state bugs at the cost of pickle overhead.

## Dependency Compatibility

### Concrete checks

1. **Interpreter flag verification**
   * CI gate: assert `sys.flags.freethreading is True`.
   * Fail fast in `conftest.py` if running tests on a non-free-threaded interpreter.

2. **Wheel ABI inspection**
   * Free-threaded wheels use ABI tag `cp314t`. Inspect installed wheels:
     ```bash
     python -c "import importlib.metadata; print([d for d in importlib.metadata.distributions() if 'cp314t' not in str(d.locate_file(''))])"
     ```
   * CI gate: parse `pip list --format=json`, assert all C-extension packages have `cp314t` in filename or are pure Python.

3. **C-extension checklist**
   * List all dependencies with compiled extensions: `pip show --files <pkg> | grep .so`.
   * Verify maintainers ship `cp314t` wheels. For internal wheels, rebuild with `—with-freethreading`.
   * Avoid packages that use C globals or rely on GIL for safety.

4. **Runtime sys.flags verification**
   * Startup check:
     ```python
     import sys
     assert sys.flags.freethreading, "Free-threaded interpreter required"
     ```
   * Pre-commit hook can lint for `sys.flags.freethreading` usage.

5. **Shared state audit**
   * Run `grep -r "global "` and `grep -r "module-level mutable"` across codebase.
   * Use `vulture` + custom checker to flag module globals.

### CI gate automation

Add a free-threading compatibility gate to `prek.toml`:

```toml
[[tools.pre-commit.hooks]]
id = python-free-thread-gate
name = Free-thread dependency compatibility
entry = python -m tools.check_free_thread_compat
language = system
files = ^(src|tests)/
```

`tools/check_free_thread_compat.py` should:
* Assert `sys.flags.freethreading`.
* Enumerate distributions, fail if any C-extension lacks `cp314t`.
* Run a smoke test importing critical dependencies.

### Hybrid compatibility strategy

Maintain a compatibility matrix:

| Package | Pure Python? | cp314t wheel? | Free-thread safe? |
|---------|--------------|---------------|-------------------|
| myapp.core | Yes | N/A | Yes |
| numpy | No | No | No — use run_in_thread() |
| orjson | No | Check | Yes — C extension releases GIL |

Gate new dependencies through a review: no free-threaded release → fallback to `InterpreterPoolExecutor` or `run_in_thread()`.

## Testing

* Run tests under both standard and free-threaded interpreters.
* Use `pytest-xdist` to expose race conditions.
* Add thread-safety property tests: run same function concurrently with varied inputs, assert deterministic output.
* Verify pickleability: `pickle.dumps(args)` for all public APIs used in parallel.

## Known limitations

* Free-threaded Python 3.14 builds are not yet universally packaged; production adoption depends on platform availability.
* C-extension ecosystem support is still maturing; reference provides compatibility checks but cannot guarantee third-party wheels.
* AWS Lambda does not ship a free-threaded runtime; guidance is for ECS/VM workloads only.
* Shared mutable state remains a footgun; free-threading does not make unsafe code safe.

## Related Documentation

* See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
* Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
* Consult `SKILL.md` for high-level skill conventions and recommendations
