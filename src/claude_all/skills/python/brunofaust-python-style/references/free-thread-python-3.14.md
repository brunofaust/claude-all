# Python 3.14 Free-Threaded — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 free-threaded builds remove the Global Interpreter Lock (GIL) that historically serialized bytecode execution across threads. The free-threaded variant is the Python 3.14 interpreter built with `--disable-gil`, often installed as `python3.14t` on Linux distributions.

The change makes the CPython interpreter itself thread-safe for pure-Python code: multiple OS threads can execute Python bytecode concurrently without interpreter-level serialization. This is distinct from the async model — free-threading enables *true* data-parallel CPU work inside threads, while async + `run_in_thread()` remains the strategy for offloading blocking I/O or C-extension work.

Key identifiers:
- `sys.freethreaded` is `True` on a free-threaded build from Python 3.13+.
- Wheels for free-threaded builds use the `cp314t` ABI tag (`t` = threaded).
- PEP 703 — "Resolving the GIL" — describes the design.

## When to use

Free-threading is not a universal default. Use it when:

- **CPU-bound pure-Python workloads** need parallelism and multiprocessing overhead is undesirable. Example: number-crunching loops, image processing in pure Python, large in-memory transformations.
- You need **shared memory between workers** without pickling overhead. Threads share the same heap; processes do not.
- You are migrating from a `concurrent.futures.ThreadPoolExecutor` that was previously GIL-limited. With a free-threaded interpreter, that pool can now run CPU-bound Python in parallel.
- You control the interpreter build and the full dependency tree.

Do *not* use free-threading as a replacement for async I/O:

- Async remains the default for I/O-bound work, network calls, and AWS SDK usage. `asyncio` + `uvloop` + `run_in_thread()` for blocking C extensions is still the project baseline.
- Free-threading does not remove locks inside C extensions. If a dependency holds internal GIL-like locks, threads will still serialize.

Mixing models is common: async event loop for I/O, with free-threaded worker threads for CPU-bound pure-Python sections.

## Pros and Cons

### Pros
- **True parallelism for pure-Python code.** CPU cores are used without process fork overhead.
- **Lower memory cost vs multiprocessing.** Threads share heap; no duplicate interpreter state.
- **Simpler code than multiprocessing.** No pickling required for shared objects; `ThreadPoolExecutor` maps directly to parallelism.
- **Fits existing threading APIs.** Standard library `threading`, `concurrent.futures.ThreadPoolExecutor` work unchanged; semantics improve rather than change.

### Cons
- **Dependency compatibility risk.** C extensions must be built for the free-threaded ABI and be thread-safe. Many libraries are not yet compatible.
- **Shared mutable state is dangerous.** Without the GIL as a serialization point, data races become possible. Immutable-by-default design, careful locking, and the project’s existing `Mapping`/`Sequence` immutable parameter rules are even more critical.
- **C-extension locks remain.** Libraries that release the GIL internally still work, but those with internal global locks will serialize.
- **Pickling / ABI constraints.** Existing wheels built for `cp314` are not compatible with `cp314t`. Installation falls back to source builds, which may fail.
- **Platform support.** Free-threaded builds are not universally packaged; CI and production must explicitly target `python3.14t`.

## Implementation

### 1. Verify interpreter

```python
import sys

print(sys.version)
print(sys.freethreaded)  # True on free-threaded build
```

For CI / pre-flight checks:

```python
if not sys.freethreaded:
    raise SystemExit("Free-threaded interpreter required for this workload")
```

### 2. Install a free-threaded build

On Debian/Ubuntu:

```bash
apt install python3.14t python3.14t-venv
python3.14t -m venv .venv-ft
```

With `uv`:

```toml
# pyproject.toml
[project]
requires-python = "==3.14.*"
```

Set `PYTHON_VERSION=3.14t` in CI matrix. The project’s `language_version` pin in `prek.toml` must point to the free-threaded interpreter for any AST checks that rely on 3.14 syntax.

### 3. Code patterns

Free-threading enables standard threading for CPU work:

```python
import concurrent.futures
from collections.abc import Mapping

def cpu_heavy(item: Mapping[str, int]) -> int:
    # Pure-Python CPU work
    total = 0
    for v in item.values():
        total += sum(1 for _ in range(v))
    return total

def process_batch(items: list[Mapping[str, int]]) -> list[int]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        # On free-threaded Python this runs in true parallel
        return list(pool.map(cpu_heavy, items))
```

Hybrid async + free-thread:

```python
import asyncio
from myapp.core.thread_pool import run_in_thread  # skill-owned wrapper

async def handle_request(payload: Mapping[str, int]) -> int:
    # I/O stays async
    # CPU-heavy pure-Python work offloaded to free-threaded pool
    result = await run_in_thread(cpu_heavy, payload)
    return result
```

Notes:
- Keep parameters immutable (`Mapping`/`Sequence`) to avoid data races.
- Avoid mutable shared globals. If shared state is required, protect with `threading.Lock` and document the invariant.
- The skill’s banned-api rule for raw `asyncio.to_thread` still applies. Use the owned `run_in_thread()` seam for consistent pool sizing and logging.
- For code that *requires* isolation, `InterpreterPoolExecutor` remains the tool for true interpreter isolation.

### 4. Project wiring

- Add a `poetry` / `uv` constraint that selects `cp314t` wheels.
- In `pyproject.toml`, ensure `requires-python` pins `==3.14.*` and CI runs the `t` interpreter.
- Update `prek.toml.example` hooks to use the free-threaded `language_version` if AST checks are run.

## Checking dependency compatibility

Free-threaded compatibility is a build-ABI + thread-safety question.

### 1. Runtime check

```python
import sys, importlib.metadata

def is_free_threaded_wheel(dist_name: str) -> bool:
    try:
        dist = importlib.metadata.distribution(dist_name)
        # Wheel filename contains cp314t
        files = dist.files or []
        return any("cp314t" in (f.name or "") for f in files)
    except Exception:
        return False
```

### 2. Inspect installed packages

```
pip list --format=freeze
```

Look for packages with `cp314` wheels but no `cp314t` variant. Packages built against `abi3` may work; pure-Python packages almost always work.

### 3. Test matrix

Run the test suite under both interpreters:

- Standard `python3.14` — baseline
- Free-threaded `python3.14t` — concurrency tests

Use `pytest-xdist` with `-n auto` to expose race conditions.

### 4. C-extension checklist

For each third-party C extension:

- Does the maintainer publish `cp314t` wheels?
- Does the library claim free-threaded support? e.g., `numpy`, `pandas`, `orjson` release notes.
- Are there known global locks? Search for “GIL” in the changelog.
- Does the library use `Py_BEGIN_CRITICAL_SECTION` correctly?

If a dependency is incompatible, options:
- Keep that dependency on the standard interpreter and isolate via `InterpreterPoolExecutor`.
- Replace with a pure-Python alternative.
- Pin to a version with free-threaded support.

### 5. Automation

Add a CI gate:

```python
# check_free_thread_compat.py
import sys
import importlib.metadata

if not sys.freethreaded:
    print("Skipping free-thread compatibility check on non-free-threaded build")
    sys.exit(0)

incompatible = []
for dist in importlib.metadata.distributions():
    name = dist.metadata["Name"]
    # heuristic: pure-Python packages have no .so/.pyd
    files = [f.name for f in (dist.files or [])]
    has_extension = any(f.name.endswith((".so", ".pyd")) for f in (dist.files or []))
    if has_extension and not any("cp314t" in f for f in files):
        incompatible.append(name)

if incompatible:
    raise SystemExit(f"Incompatible C extensions for free-threading: {incompatible}")
```

Run this gate in CI alongside mypy/ruff.

## Integration with brunofaust-python-style

- Python 3.14+ baseline remains mandatory. Free-threading is an *optional* performance mode built on top of that baseline.
- Immutable parameter types, `async-first` design, and `run_in_thread()` ownership are unchanged.
- Banned APIs (`asyncio.to_thread`, raw `ThreadPoolExecutor`) remain banned. The owned `run_in_thread()` and `thread_pool.py` remain the single seam.
- For CPU-bound work that cannot be made thread-safe, prefer `InterpreterPoolExecutor` over free-threading.
- Document any code that relies on free-threading with a module-level comment: `# Requires free-threaded Python 3.14 build`.

## Known limitations

- Most AWS SDKs (`aiobotocore`) are I/O bound and benefit little from free-threading; async remains correct.
- Polars and NumPy releases for free-threading are still maturing; verify wheel availability before adoption.
- Thread-safety bugs are harder to reproduce than GIL-serialized bugs. Invest in stress tests and property-based testing for shared state.
- Lambda runtime does not currently ship a free-threaded build; this pattern is for ECS/VM workloads.

Refer to `references/async-patterns.md` for `run_in_thread()` and `InterpreterPoolExecutor` guidance, and `references/enforcement.md` for banned-api rules regarding threading mechanisms.
