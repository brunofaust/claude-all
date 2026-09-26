# Free-threading (PEP 703) — Python 3.14 `--disable-gil` builds

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

**Free-threading** (PEP 703) is an *optional* build configuration of CPython 3.14+ that disables the Global Interpreter Lock (GIL). It is **not** the standard Python 3.14 release — you must install a special `--disable-gil` build (e.g., `python3.14t` / `cp314t` wheels). The standard 3.14 interpreter still has the GIL.

This reference covers:
- When free-threading makes sense vs. the existing `InterpreterPoolExecutor` / `run_in_thread()` patterns
- Pros, cons, and practical constraints
- Implementation patterns and runtime detection
- Dependency compatibility verification
- Platform limitations (AWS Lambda, managed services)
- Migration guidance for existing codebases

---

## Free-threading vs. Subinterpreters vs. Thread Pool — Decision Matrix

| Feature | Free-threading (`--disable-gil`) | `InterpreterPoolExecutor` (PEP 734) | `run_in_thread()` (ThreadPoolExecutor) |
|---------|----------------------------------|-------------------------------------|----------------------------------------|
| **Parallelism model** | True shared-memory threads, no GIL | Multiple interpreters, each with own GIL | Threads with GIL (released for C extensions / I/O) |
| **State sharing** | Full shared mutable state (use locks) | Isolated — only picklable / shareable types | Full shared mutable state (use locks) |
| **C-extension support** | Requires thread-safe extensions / `cp314t` wheels | Limited — extensions with global state may break | Works with all extensions (GIL released for blocking calls) |
| **Overhead** | Low (single process, native threads) | Medium (interpreter startup, IPC for data) | Low (thread pool reuse) |
| **Best for** | CPU-bound pure Python + shared state | CPU-bound pure Python, **no shared state** | Blocking I/O, C extensions that release GIL (Polars, DeltaTable) |
| **Python version** | 3.14+ `--disable-gil` build only | 3.14+ (standard build) | 3.11+ (all builds) |
| **Platform availability** | Limited (no AWS Lambda, some managed services) | Standard 3.14+ — widely available | Universal |

### When to choose what — the skill's recommendation

| Situation | Recommended approach |
|-----------|---------------------|
| **CPU-bound pure Python** (parsing, math, transformations) | **Default: `InterpreterPoolExecutor`** — works on standard 3.14, true parallelism, no shared-state complexity |
| **CPU-bound pure Python + need shared mutable state** | **Free-threading** — if you control the runtime and dependencies are compatible |
| **Blocking I/O / C extensions that release GIL** (Polars, DeltaTable, file I/O) | **`run_in_thread()`** — simplest, lowest overhead, works everywhere |
| **C extensions that *don't* release GIL** (legacy numeric libs) | **Free-threading** — only way to parallelize without process pool |
| **AWS Lambda / managed runtimes** | **`InterpreterPoolExecutor` or `run_in_thread()`** — free-threaded build not available |
| **Greenfield, self-hosted (ECS/VM/K8s), full dependency control** | Free-threading **viable** — evaluate per [Compatibility Checklist](#dependency-compatibility-checklist) |

> **Rule of thumb**: Start with `InterpreterPoolExecutor` for CPU-bound work and `run_in_thread()` for blocking I/O. Adopt free-threading only when you have a concrete need for shared-memory parallelism *and* you control the runtime + dependency chain.

---

## Pros and Cons

### Pros

| Benefit | Detail |
|---------|--------|
| **True shared-memory parallelism** | Multiple threads execute Python bytecode simultaneously — no GIL serialization. |
| **Lower overhead than multiprocessing** | No process spawn, no pickle/IPC, shared address space. |
| **Simpler shared state** | Direct access to mutable objects (with locks/`threading` primitives) — no pickling constraints. |
| **Existing threading code "just works" faster** | `threading.Thread`, `ThreadPoolExecutor`, `asyncio.to_thread` automatically parallelize. |
| **Better memory efficiency** | Single process, no duplicated interpreter state. |

### Cons

| Drawback | Detail |
|----------|--------|
| **Special build required** | Not the default `python3.14` — need `python3.14t` / `cpython-3.14-free-threaded`. |
| **C-extension compatibility** | Extensions must be rebuilt for `cp314t` ABI and be thread-safe. Many popular libs (numpy, pandas, polars, lxml, cryptography) *have* free-threaded wheels, but not all. |
| **Thread-safety burden shifts to you** | Data races are now possible in pure Python. Must use `threading.Lock`, `RLock`, `Queue`, `asyncio.Lock` (in async contexts), or thread-safe collections. |
| **Platform gaps** | **AWS Lambda does not ship a free-threaded Python 3.14 runtime.** Managed services (Cloud Run, Fargate, Azure Functions) may lag. |
| **Debugging complexity** | Heisenbugs from data races; tools like `threading` sanitizers / `pyrace` needed. |
| **Single-process ceiling** | Still bounded by one machine — for horizontal scale, you need multiple processes anyway. |
| **Ecosystem maturity** | 3.14 free-threading is new (Oct 2025); best practices and tooling still evolving. |

---

## Runtime Detection

Always detect at runtime — do not assume the free-threaded build.

```python
import sys
import sysconfig


def is_free_threaded() -> bool:
    """
    Return True if running on a free-threaded (--disable-gil) build.

    PEP 703: `sysconfig.get_config_var("Py_GIL_DISABLED")` is 1 on free-threaded builds.
    `sys._is_gil_enabled()` (3.13+) returns False when GIL is disabled.
    """
    # Primary: build-time config var (available even if GIL re-enabled at runtime)
    gil_disabled = sysconfig.get_config_var("Py_GIL_DISABLED")
    if gil_disabled == 1:
        return True

    # Secondary: runtime check (3.13+) — GIL can be re-enabled via PYTHON_GIL=1 env var
    if hasattr(sys, "_is_gil_enabled"):
        return not sys._is_gil_enabled()

    return False


def gil_status() -> str:
    """Human-readable GIL status for logging / diagnostics."""
    if is_free_threaded():
        if hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled():
            return "free-threaded (GIL disabled)"
        return "free-threaded build (GIL re-enabled at runtime via PYTHON_GIL=1)"
    return "standard build (GIL enabled)"
```

### Conditional Patterns

Use detection to choose the right concurrency primitive at runtime:

```python
from concurrent.futures import InterpreterPoolExecutor, ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from concurrent.futures import Executor


def get_cpu_executor(max_workers: int | None = None) -> "Executor":
    """
    Return the best CPU-bound executor for the current runtime.

    - Free-threaded: ThreadPoolExecutor (true parallelism, shared memory)
    - Standard 3.14+: InterpreterPoolExecutor (subinterpreters, isolated)
    - <3.14: ThreadPoolExecutor (GIL-limited, but works for C-extensions releasing GIL)
    """
    if is_free_threaded():
        # Free-threaded: native threads parallelize Python code
        return ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="cpu-pool")

    # Standard 3.14+: subinterpreters for CPU-bound pure Python
    if sys.version_info >= (3, 14):
        try:
            return InterpreterPoolExecutor(max_workers=max_workers)
        except Exception:
            pass  # Fall through to ThreadPoolExecutor

    # Pre-3.14 or InterpreterPoolExecutor unavailable
    return ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="cpu-pool")
```

---

## Dependency Compatibility Checklist

Free-threading requires **every C extension** in your dependency tree to:
1. Publish `cp314t` (free-threaded) wheels on PyPI, **AND**
2. Be thread-safe (no global mutable state without locks).

### 1. Check for `cp314t` wheels on PyPI

```bash
# For a specific package
pip index versions numpy --verbose 2>/dev/null | grep cp314t

# Or use pip's --platform to simulate free-threaded resolution
pip download --python-version 3.14 --platform manylinux_2_28_x86_64 --abi cp314t numpy -d /tmp/check --no-deps 2>&1 | head -20
```

**Automated check script** (add to CI):

```python
#!/usr/bin/env python3
"""check_free_threaded_deps.py — Verify all dependencies have cp314t wheels."""
import json
import subprocess
import sys
from packaging.requirements import Requirement

def has_cp314t_wheel(package: str) -> bool:
    """Check if a package has cp314t wheels on PyPI via pip index."""
    try:
        result = subprocess.run(
            ["pip", "index", "versions", package, "--verbose"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return "cp314t" in result.stdout
    except Exception:
        return False

def main():
    # Read from pyproject.toml or requirements.txt
    # Example: parse [project].dependencies + [project.optional-dependencies]
    import tomllib
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)

    deps = data.get("project", {}).get("dependencies", [])
    optional = data.get("project", {}).get("optional-dependencies", {})
    for extra_deps in optional.values():
        deps.extend(extra_deps)

    missing = []
    for dep in deps:
        req = Requirement(dep)
        name = req.name
        if not has_cp314t_wheel(name):
            missing.append(name)

    if missing:
        print("❌ Missing cp314t wheels:", ", ".join(missing))
        sys.exit(1)
    print("✅ All dependencies have cp314t wheels")

if __name__ == "__main__":
    main()
```

### 2. Known compatible / incompatible ecosystem (as of 3.14 release)

| Package | Free-threaded wheels? | Notes |
|---------|----------------------|-------|
| **numpy** | ✅ | `cp314t` wheels since 1.26+ |
| **pandas** | ✅ | Requires numpy `cp314t` |
| **polars** | ✅ | Rust backend, thread-safe; `cp314t` wheels |
| **pyarrow** | ✅ | `cp314t` wheels |
| **lxml** | ✅ | `cp314t` wheels |
| **cryptography** | ✅ | `cp314t` wheels |
| **pydantic** | ✅ | Pure Python + `cp314t` for core |
| **orjson** | ✅ | Rust, thread-safe |
| **uvloop** | ✅ | `cp314t` wheels |
| **aiobotocore / boto3** | ✅ | Pure Python |
| **structlog** | ✅ | Pure Python |
| **cachebox** | ✅ | Pure Python |
| **xxhash** | ✅ | `cp314t` wheels |
| **psycopg2** | ⚠️ | Use `psycopg[binary]` (psycopg3) — `cp314t` wheels |
| **SQLAlchemy** | ✅ | Pure Python |
| **redis-py** | ✅ | Pure Python |
| **httpx** | ✅ | Pure Python |

> **Check your specific versions** — run the automated script above in CI against your locked dependencies.

### 3. Runtime thread-safety verification

Even with `cp314t` wheels, some extensions have global state that isn't thread-safe. Verify at runtime:

```python
import threading
import sys
from concurrent.futures import ThreadPoolExecutor


def stress_test_extension(module_name: str, iterations: int = 1000) -> bool:
    """
    Basic smoke test: call the extension concurrently from multiple threads.
    Not a proof of thread-safety, but catches obvious global-state crashes.
    """
    mod = __import__(module_name)
    errors: list[Exception] = []

    def worker():
        try:
            # Exercise common APIs — adapt per module
            if module_name == "polars":
                import polars as pl
                for _ in range(10):
                    df = pl.DataFrame({"x": range(100)})
                    _ = df.select(pl.col("x").sum()).item()
            elif module_name == "numpy":
                import numpy as np
                for _ in range(10):
                    _ = np.random.random(1000).sum()
            elif module_name == "pyarrow":
                import pyarrow as pa
                for _ in range(10):
                    _ = pa.array(range(100)).sum()
            # Add per-module exercise paths as needed
        except Exception as e:
            errors.append(e)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda _: worker(), range(iterations)))

    if errors:
        print(f"❌ {module_name}: {len(errors)} errors under concurrent load")
        for e in errors[:3]:
            print(f"   {type(e).__name__}: {e}")
        return False
    print(f"✅ {module_name}: no errors in stress test")
    return True


if __name__ == "__main__" and is_free_threaded():
    for mod in ["polars", "numpy", "pyarrow", "pydantic", "orjson"]:
        stress_test_extension(mod)
```

### 4. CI Testing Strategy

**Run tests on both builds** in CI:

```yaml
# .github/workflows/test.yml
jobs:
  test-standard:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - run: uv sync --all-extras
      - run: uv run pytest -n auto

  test-free-threaded:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: "3.14t"  # or "3.14-free-threaded"
      - run: uv sync --all-extras
      - run: uv run pytest -n auto
      - run: python scripts/check_free_threaded_deps.py
```

> **Note**: GitHub Actions `setup-python` supports `3.14t` / `3.14-free-threaded` as of 2025. For self-hosted runners, install from `https://github.com/astral-sh/python-build-standalone` or use `uv python install 3.14t`.

---

## Implementation Patterns

### 1. Thread-safe data structures

Under free-threading, **all shared mutable state needs synchronization**.

```python
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")


@dataclass
class ThreadSafeCache[T]:
    """Thread-safe LRU cache — use instead of dict for shared caches."""

    _data: dict[str, T] = field(default_factory=dict, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _max_size: int = field(default=1000, init=False)

    def get(self, key: str) -> T | None:
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, value: T) -> None:
        with self._lock:
            if len(self._data) >= self._max_size:
                # Simple LRU: pop first item (dict preserves insertion order in 3.7+)
                self._data.pop(next(iter(self._data)))
            self._data[key] = value

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._data
```

**Prefer `queue.Queue` / `asyncio.Queue` over raw `list` / `dict` for cross-thread communication.**

### 2. Locking discipline

```python
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator


class LockOrder:
    """
    Document and enforce a global lock acquisition order.

    Any code taking multiple locks MUST acquire them in this order.
    Violation = latent deadlock.
    """
    # Order: lower number = acquire first
    CACHE = 10
    DB_POOL = 20
    EXTERNAL_API = 30
    FILE_SYSTEM = 40

    _held_locks: threading.local = threading.local()

    @classmethod
    @contextmanager
    def acquire(cls, *locks: tuple[int, threading.Lock]) -> "Generator[None, None, None]":
        """
        Acquire multiple locks in global order.

        Args:
            locks: Tuples of (order_rank, lock_instance)

        Example:
            with LockOrder.acquire(
                (LockOrder.CACHE, cache_lock),
                (LockOrder.DB_POOL, db_lock),
            ):
                ...
        """
        # Sort by global order
        sorted_locks = sorted(locks, key=lambda x: x[0])

        # Check for lock-order inversion
        held = getattr(cls._held_locks, "stack", [])
        for rank, _ in sorted_locks:
            for held_rank, _ in held:
                if held_rank >= rank:
                    raise RuntimeError(
                        f"Lock order inversion: trying to acquire rank {rank} "
                        f"while holding rank {held_rank}. Global order must be ascending."
                    )

        try:
            for _, lock in sorted_locks:
                lock.acquire()
                held.append((rank, lock))
            cls._held_locks.stack = held
            yield
        finally:
            for _, lock in reversed(sorted_locks):
                lock.release()
            held.clear()
```

### 3. Adapting `run_in_thread()` for free-threading

The existing `run_in_thread()` wrapper (from `async-patterns.md`) works unchanged on free-threaded builds — it still offloads to a thread pool. On free-threaded builds, those threads run in parallel.

**No code change required** for the basic pattern. However, you may want to tune pool sizing:

```python
# thread.py — adjust pool sizing for free-threaded builds
import os
import sysconfig
from concurrent.futures import ThreadPoolExecutor

# CPU count is the right baseline for free-threaded (true parallelism)
# For standard builds, keep smaller since Python threads don't parallelize CPU work
def _default_max_workers() -> int:
    if is_free_threaded():
        return min(32, (os.cpu_count() or 4) * 2)  # Higher for true parallelism
    return 10  # Standard: GIL limits CPU parallelism


BLOCKING_THREADPOOL: ThreadPoolExecutor = ThreadPoolExecutor(
    max_workers=_default_max_workers(),
    thread_name_prefix="blocking-pool",
)
```

### 4. Async code under free-threading

`asyncio` **still runs on a single thread** (the event loop thread). Free-threading does not make `asyncio` multi-threaded.

- `asyncio.TaskGroup`, `asyncio.gather`, `asyncio.Semaphore` work exactly as before.
- `run_in_thread()` still offloads blocking work to the thread pool.
- The difference: **the thread pool workers now run Python bytecode in parallel**.

```python
# This pattern is unchanged — but on free-threaded, the worker threads
# can execute pure Python CPU work in parallel, not just release GIL for C calls.
async def process_batch(items: Sequence[Item]) -> list[Result]:
    semaphore = asyncio.Semaphore(50)

    async def worker(item: Item) -> Result:
        async with semaphore:
            # On free-threaded: this runs in parallel across threads
            # On standard: this serializes on GIL unless it calls C extensions
            return await run_in_thread(cpu_intensive_transform, item)

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(worker(item)) for item in items]

    return [t.result() for t in tasks]
```

---

## Platform Support Matrix

| Platform / Runtime | Free-threaded build available? | Notes |
|-------------------|--------------------------------|-------|
| **AWS Lambda** | ❌ **No** (as of 2025) | Only standard `python3.14` runtime. Use container image with custom build if needed (cold start penalty). |
| **AWS ECS / EKS (EC2/Fargate)** | ✅ | Bring your own container — install `python3.14t` via `uv` or standalone builds. |
| **Google Cloud Run** | ⚠️ | Custom containers only; no managed free-threaded runtime. |
| **Azure Container Apps** | ⚠️ | Custom containers only. |
| **Kubernetes (self-managed)** | ✅ | Full control — use `python:3.14t-slim` or `ghcr.io/astral-sh/python:3.14t`. |
| **GitHub Actions** | ✅ | `setup-python@v5` supports `3.14t` / `3.14-free-threaded`. |
| **Local development (macOS/Linux)** | ✅ | `uv python install 3.14t` or `pyenv install 3.14t`. |

### Container base images

```dockerfile
# Option 1: Astral's standalone builds (small, fast)
FROM ghcr.io/astral-sh/python:3.14t-slim

# Option 2: Official CPython (larger, full stdlib)
# Not yet available as free-threaded on Docker Hub as of 2025

# Option 3: Build from source (slow, full control)
# FROM python:3.14-slim
# RUN ./configure --disable-gil && make -j$(nproc) && make install
```

> **Recommendation**: For AWS Lambda, **stick with standard 3.14 + `InterpreterPoolExecutor` / `run_in_thread()`**. The cold-start cost of a custom container with free-threaded Python outweighs the benefit for typical Lambda workloads.

---

## Migration Guide

### From `InterpreterPoolExecutor` to Free-threading

| Aspect | `InterpreterPoolExecutor` | Free-threaded `ThreadPoolExecutor` |
|--------|---------------------------|-----------------------------------|
| **Data sharing** | Pickle / shareable types only | Direct shared memory (with locks) |
| **Global state** | Each interpreter isolated | Single process — global state shared |
| **C extensions** | May break with global state | Works if thread-safe + `cp314t` wheels |
| **Code changes** | Minimal (API-compatible) | Minimal (same `Executor` interface) |

**Migration steps**:
1. Verify all deps have `cp314t` wheels (run compatibility checklist)
2. Add runtime detection (`is_free_threaded()`)
3. Switch executor factory to `get_cpu_executor()` (see [Runtime Detection](#runtime-detection))
4. **Audit shared mutable state** — any module-level `dict`/`list` accessed from workers now needs locks
5. Run test suite on free-threaded build in CI
6. Add stress tests for concurrent access patterns

### From `run_in_thread()` to Free-threading

**No migration needed** — `run_in_thread()` works identically. The thread pool it uses (`BLOCKING_THREADPOOL`) automatically benefits from free-threading.

If you have CPU-bound pure Python work currently in `run_in_thread()`:
- It **already runs in threads** — on free-threaded, it parallelizes automatically
- Consider moving to `get_cpu_executor()` for semantic clarity (CPU pool vs blocking pool)

### Greenfield Projects

For new projects targeting free-threading from day one:

1. **Pin the interpreter** in `pyproject.toml` / `.python-version`:
   ```toml
   [project]
   requires-python = ">=3.14"
   # Document: this project requires the free-threaded build (cp314t)
   ```

2. **Configure CI** to test on `3.14t` (see [CI Testing Strategy](#4-ci-testing-strategy))

3. **Default to thread-safe patterns**:
   - Use `threading.Lock` / `RLock` for shared mutable state
   - Prefer `queue.Queue` / `asyncio.Queue` for cross-thread communication
   - Avoid module-level mutable globals — use dependency injection

4. **Document the requirement** in `README.md` and `CLAUDE.md`:
   > This project requires the **free-threaded CPython 3.14 build** (`python3.14t` / `cp314t`).
   > Install with `uv python install 3.14t` or use the `ghcr.io/astral-sh/python:3.14t-slim` container.

---

## Enforcement & Gates

### Ruff `banned-api` — no change needed

The existing ban on raw `asyncio.to_thread` and `concurrent.futures.ThreadPoolExecutor` (enforced via `TID251` in `enforcement.md`) **still applies**. Free-threading doesn't change the rule: **all thread offload goes through `run_in_thread()`** so pool sizing, naming, and leak tracking remain centralized.

### New checkers to consider

| Check | Implementation |
|-------|----------------|
| **Runtime GIL check in CI** | Fail if free-threaded tests run on standard build (or vice versa) |
| **Dependency wheel check** | `check_free_threaded_deps.py` in CI (see [Compatibility Checklist](#dependency-compatibility-checklist)) |
| **Thread-safety audit** | AST checker flagging unsynchronized shared mutable state (module-level `dict`/`list` written from multiple threads) — future work |

---

## Quick Reference Card

| Question | Answer |
|----------|--------|
| **Is free-threading the default in 3.14?** | No — separate `--disable-gil` build (`python3.14t`). |
| **Does it replace `InterpreterPoolExecutor`?** | No — different trade-offs. `InterpreterPoolExecutor` works on standard 3.14; free-threading needs special build. |
| **Does it replace `run_in_thread()`?** | No — `run_in_thread()` is still the approved offload seam. It benefits automatically. |
| **Can I use it on AWS Lambda?** | No — Lambda doesn't ship the free-threaded runtime. |
| **Do I need to rewrite my async code?** | No — `asyncio` unchanged. Thread pool workers parallelize. |
| **How do I check if a dep is compatible?** | 1. `pip index versions <pkg> --verbose | grep cp314t` 2. Run stress test 3. Test in CI on `3.14t`. |
| **What if a dep lacks `cp314t` wheels?** | You cannot use free-threading — fall back to standard 3.14 + `InterpreterPoolExecutor`. |
| **Is `threading.Lock` enough for shared state?** | Yes, but prefer higher-level: `queue.Queue`, `asyncio.Queue`, `cachebox` (thread-safe). |

---

## Related References

- [`async-patterns.md`](async-patterns.md) — `run_in_thread()`, `InterpreterPoolExecutor`, `TaskGroup`, semaphores
- [`enforcement.md`](enforcement.md) — banned-api rules for `asyncio.to_thread` / `ThreadPoolExecutor`
- [`architecture.md`](architecture.md) — lock ordering, concurrency discipline
- [`testing.md`](testing.md) — concurrent test patterns, xdist isolation
