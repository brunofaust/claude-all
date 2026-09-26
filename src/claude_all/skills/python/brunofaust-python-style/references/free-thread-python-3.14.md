# Free-threaded Python 3.14 — reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduces **free-threaded builds** (configured with `--disable-gil` / `--enable-freethreading`), where the Global Interpreter Lock (GIL) is removed and multiple threads can execute Python bytecode simultaneously. This is distinct from:

| Mechanism | Parallelism model | GIL behaviour | Overhead | Shared state |
|-----------|-------------------|---------------|----------|--------------|
| **Free-threaded build** | True multi-threaded | **No GIL** | None (single process) | ✅ Shared by default — **unsafe without discipline** |
| `InterpreterPoolExecutor` (PEP 734) | Subinterpreters | **One GIL per subinterpreter** | Low (shared process, separate GILs) | ❌ Isolated — only picklable data crosses boundaries |
| `ProcessPoolExecutor` | Separate processes | One GIL per process | High (IPC, memory copy) | ❌ Isolated — only picklable data crosses boundaries |
| `run_in_thread()` (thread pool) | Threads | **GIL held** — C extensions release it | Low | ✅ Shared — same caveats as free-threaded |

**Key point**: A free-threaded build removes the GIL entirely within a single interpreter. This enables true CPU parallelism for **pure Python code** without subinterpreter isolation overhead. However:

- **C extensions** must be rebuilt for the free-threaded ABI (`cp314t` wheel tag). Extensions that assume the GIL (most of the ecosystem) will crash or corrupt data.
- **Shared mutable state** is now a real race condition — free-threading **exposes** races rather than fixing them. The same locking discipline required for multi-process code applies.
- **Platform availability**: Free-threaded Python 3.14 builds are not universally packaged. AWS Lambda does **not** ship a free-threaded runtime. Production use is limited to ECS, VMs, or self-managed containers where you control the interpreter build.

This reference assumes the **free-threaded build** (not subinterpreters). For `InterpreterPoolExecutor` guidance, see [`async-patterns.md`](async-patterns.md#interpreterpoolexecutor).

## When to Use

| Situation | Use free-threaded build? |
|-----------|--------------------------|
| **CPU-bound pure Python** (parsing, serialization, math, graph algorithms) | ✅ Yes — true parallelism without subinterpreter pickling overhead |
| **Mixed CPU + I/O** (async HTTP fan-out + local transformation) | ✅ Yes — `asyncio` + threads in one process, no GIL contention |
| **C-extension-heavy workloads** (Polars, NumPy, DeltaTable, PyArrow) | ❌ No — use `run_in_thread()`; these already release the GIL and need the GIL-enabled ABI |
| **Blocking I/O** (file, network) | ❌ No — use `run_in_thread()`; simpler, works on any build |
| **AWS Lambda** | ❌ Not available — Lambda runtime is GIL-enabled |
| **Shared mutable state across workers** | ⚠️ Only with explicit locking — free-threading makes races real, not theoretical |

**Default for this skill**: Continue using `asyncio` + `run_in_thread()` for blocking/C-extension work. Adopt free-threaded builds **only** when you have measured CPU-bound pure-Python bottlenecks that `InterpreterPoolExecutor` cannot satisfy due to pickling overhead or shared-state needs.

## Pros and Cons

### Pros

| Benefit | Detail |
|---------|--------|
| **True CPU parallelism for pure Python** | No GIL serialization — numerical loops, parsing, serialization scale linearly with cores |
| **Lower overhead than subinterpreters** | No pickling for shared data; direct memory access |
| **Unified async + threads** | `asyncio` event loop runs alongside CPU threads in one process; no cross-process serialization |
| **Simpler deployment than multiprocessing** | Single container, single memory space, no IPC |

### Cons

| Drawback | Detail |
|----------|--------|
| **C-extension ecosystem immature** | Most wheels are `cp314` (GIL-enabled). Free-threaded needs `cp314t`. Missing wheels = build from source or fallback |
| **Shared mutable state is unsafe** | Dicts, lists, custom objects — concurrent mutation corrupts state. You **must** use `threading.Lock`, `asyncio.Lock` (in thread context), or immutable patterns |
| **No Lambda support** | AWS Lambda does not provide a free-threaded runtime |
| **Debugging complexity** | Data races are non-deterministic; tooling (TSan, `threading` debug) is less mature than GIL-era |
| **Not a drop-in replacement** | Code written assuming GIL safety (lazy init, cached globals, `list.append` atomicity) will break |

## Implementation

### Prerequisites

```bash
# Install free-threaded Python 3.14 (example with uv)
uv python install 3.14t  # 't' suffix = free-threaded build

# Verify
python -c "import sysconfig; print(sysconfig.get_config_var('Py_GIL_DISABLED'))"
# Should print 1
```

### Pattern 1: Pure CPU-bound parallelism (basic)

Use `concurrent.futures.ThreadPoolExecutor` directly — on a free-threaded build, threads run in parallel without GIL contention.

```python
"""
cpu_parallel.py — Pure Python CPU parallelism on free-threaded build.

This pattern replaces InterpreterPoolExecutor when:
- Workload is pure Python (no C extensions)
- Shared read-only data is large (avoids pickling overhead)
- You need fine-grained sharing of mutable state with explicit locking
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Final
import time


# Example: parallel Mandelbrot computation (pure Python, CPU-bound)
def mandelbrot_chunk(
    y_start: int,
    y_end: int,
    width: int,
    height: int,
    max_iter: int,
    result: list[list[int]],
    lock: Lock,
) -> None:
    """Compute a horizontal slice of the Mandelbrot set."""
    for y in range(y_start, y_end):
        row = []
        for x in range(width):
            c = complex(
                (x - width / 2) * 4.0 / width,
                (y - height / 2) * 4.0 / height,
            )
            z = 0
            for i in range(max_iter):
                if abs(z) > 2:
                    break
                z = z * z + c
            row.append(i)
        with lock:
            result[y] = row


def compute_mandelbrot_parallel(
    width: int = 800,
    height: int = 600,
    max_iter: int = 100,
    workers: int = 8,
) -> list[list[int]]:
    """
    Compute Mandelbrot set in parallel using free-threaded threads.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        max_iter: Maximum iterations per pixel.
        workers: Number of parallel threads.

    Returns:
        2D list of iteration counts.
    """
    result: list[list[int]] = [[] for _ in range(height)]
    lock = Lock()
    chunk_size = height // workers

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = []
        for i in range(workers):
            y_start = i * chunk_size
            y_end = height if i == workers - 1 else (i + 1) * chunk_size
            futures.append(
                executor.submit(
                    mandelbrot_chunk,
                    y_start,
                    y_end,
                    width,
                    height,
                    max_iter,
                    result,
                    lock,
                )
            )
        # Wait for completion
        for f in futures:
            f.result()

    return result


if __name__ == "__main__":
    start = time.perf_counter()
    img = compute_mandelbrot_parallel(workers=8)
    elapsed = time.perf_counter() - start
    print(f"Computed {len(img)}x{len(img[0])} in {elapsed:.2f}s")
```

**Key points**:
- `ThreadPoolExecutor` (not `InterpreterPoolExecutor`) — threads share memory directly
- Explicit `Lock` for any shared mutable writes (`result[y] = row`)
- Read-only data (constants, config) is freely shared without locking
- Workers = CPU cores (no GIL serialization)

### Pattern 2: Hybrid async I/O + CPU threads

Combine `asyncio` for I/O-bound fan-out with free-threaded threads for CPU-bound post-processing.

```python
"""
hybrid_async_cpu.py — Async I/O + free-threaded CPU parallelism.

Typical pattern: fetch many HTTP responses async, then CPU-process them in parallel.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Final
import httpx


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    status: int
    body: bytes


@dataclass(frozen=True, slots=True)
class ProcessedItem:
    url: str
    word_count: int
    checksum: str


CPU_POOL: Final[ThreadPoolExecutor] = ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="cpu-pool",
)


async def fetch_all(urls: list[str]) -> list[FetchResult]:
    """Fetch all URLs concurrently using async HTTP."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = [client.get(url) for url in urls]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[FetchResult] = []
    for url, resp in zip(urls, responses, strict=True):
        if isinstance(resp, Exception):
            results.append(FetchResult(url=url, status=0, body=b""))
        else:
            results.append(FetchResult(url=url, status=resp.status_code, body=resp.content))
    return results


def cpu_process_item(item: FetchResult) -> ProcessedItem:
    """
    CPU-bound processing — runs in free-threaded thread pool.

    This function executes in a thread WITHOUT the GIL on a free-threaded build.
    Pure Python work here (JSON parsing, string processing, hashing) scales across cores.
    """
    import hashlib
    import json

    text = item.body.decode("utf-8", errors="ignore")
    word_count = len(text.split())
    checksum = hashlib.sha256(item.body).hexdigest()[:16]

    # Simulate additional CPU work (e.g., JSON parsing, transformation)
    if item.status == 200 and text.strip().startswith("{"):
        try:
            json.loads(text)  # Parse to validate
        except json.JSONDecodeError:
            pass

    return ProcessedItem(
        url=item.url,
        word_count=word_count,
        checksum=checksum,
    )


async def process_batch(urls: list[str]) -> list[ProcessedItem]:
    """
    Full pipeline: async fetch → parallel CPU process.

    The async phase fans out I/O. The CPU phase runs in ThreadPoolExecutor
    which, on a free-threaded build, achieves true parallelism.
    """
    loop = asyncio.get_running_loop()

    # Phase 1: Async I/O
    fetched = await fetch_all(urls)

    # Phase 2: Parallel CPU (free-threaded — no GIL)
    cpu_futures = [
        loop.run_in_executor(CPU_POOL, cpu_process_item, item)
        for item in fetched
    ]
    processed = await asyncio.gather(*cpu_futures)

    return processed


async def main() -> None:
    urls = [
        "https://httpbin.org/json",
        "https://httpbin.org/html",
        "https://httpbin.org/xml",
        # ... more URLs
    ]
    results = await process_batch(urls)
    for r in results:
        print(f"{r.url}: {r.word_count} words, {r.checksum}")


if __name__ == "__main__":
    asyncio.run(main())
```

**Key points**:
- `asyncio` handles I/O fan-out (HTTP, DB, queue)
- `ThreadPoolExecutor` handles CPU post-processing
- On free-threaded build: CPU phase runs in true parallel
- On GIL-enabled build: CPU phase serializes (fallback still works)
- `run_in_executor` bridges async ↔ thread boundary

### Pattern 3: Shared read-only cache with mutable updates

Free-threading allows efficient shared caches — reads are lock-free, writes use fine-grained locks.

```python
"""
shared_cache.py — Lock-free reads, locked writes on free-threaded build.

Demonstrates a pattern where free-threading shines: a large read-mostly
data structure shared across threads without pickling overhead.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from typing import Final
import time


class SharedCache:
    """
    Thread-safe cache optimized for free-threaded builds.

    Reads are lock-free (dict get is atomic in CPython).
    Writes use a single lock — acceptable for write-rare workloads.
    For write-heavy workloads, use a sharded lock or `concurrent.futures` map.
    """

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self._lock = RLock()

    def get(self, key: str) -> bytes | None:
        """Lock-free read — atomic in CPython (free-threaded or not)."""
        return self._data.get(key)

    def set(self, key: str, value: bytes) -> None:
        """Locked write."""
        with self._lock:
            self._data[key] = value

    def compute_if_absent(self, key: str, factory: callable) -> bytes:
        """Get or compute — double-checked locking pattern."""
        # Fast path: lock-free read
        val = self._data.get(key)
        if val is not None:
            return val

        # Slow path: acquire lock, re-check, compute
        with self._lock:
            val = self._data.get(key)
            if val is not None:
                return val
            val = factory(key)
            self._data[key] = val
            return val


# Example: expensive pure-Python computation cached across threads
CACHE: Final[SharedCache] = SharedCache()


def expensive_computation(key: str) -> bytes:
    """Simulate CPU-bound pure-Python work (e.g., serialization, hashing)."""
    import hashlib

    # Simulate work
    data = key.encode() * 1000
    for _ in range(100):
        data = hashlib.sha256(data).digest()
    return data


def worker(key: str) -> bytes:
    return CACHE.compute_if_absent(key, expensive_computation)


def run_benchmark(keys: list[str], workers: int = 8) -> float:
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(worker, keys))
    return time.perf_counter() - start


if __name__ == "__main__":
    test_keys = [f"key-{i}" for i in range(50)]
    # First run: cold cache
    t1 = run_benchmark(test_keys)
    # Second run: warm cache (lock-free reads)
    t2 = run_benchmark(test_keys)
    print(f"Cold: {t1:.2f}s, Warm: {t2:.2f}s, Speedup: {t1/t2:.1f}x")
```

### Pattern 4: Integrating with `run_in_thread()` for C extensions

Free-threaded build + C extensions that release the GIL = use `run_in_thread()` for the C-extension calls, free threads for pure Python.

```python
"""
mixed_workload.py — Free-threaded pure Python + run_in_thread() for C extensions.

This is the recommended hybrid for real workloads: Polars/NumPy in threads,
pure Python transformations in free-threaded pool.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Final
import polars as pl

# Free-threaded pool for pure Python CPU work
CPU_POOL: Final[ThreadPoolExecutor] = ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="cpu-pool",
)

# run_in_thread pool for blocking C extensions (from async-patterns.md)
# This uses the skill's run_in_thread() which manages its own pool
from myapp.core.thread_pool import run_in_thread


async def process_parquet_files(paths: list[Path]) -> pl.DataFrame:
    """
    Process multiple Parquet files: read in threads (C extension),
    transform in free-threaded pool (pure Python).
    """
    loop = asyncio.get_running_loop()

    # Phase 1: Read Parquet files — Polars releases GIL, use run_in_thread
    # (This works on both GIL and free-threaded builds)
    read_futures = [
        loop.run_in_executor(None, pl.read_parquet, str(p)) for p in paths
    ]
    dataframes = await asyncio.gather(*read_futures)

    # Phase 2: Pure Python transformation — free-threaded parallelism
    def transform(df: pl.DataFrame) -> pl.DataFrame:
        # Pure Python work: custom logic, string processing, etc.
        # On free-threaded build, this runs in true parallel
        return df.with_columns(
            pl.col("text").str.to_lowercase().alias("normalized")
        )

    transform_futures = [
        loop.run_in_executor(CPU_POOL, transform, df) for df in dataframes
    ]
    transformed = await asyncio.gather(*transform_futures)

    # Phase 3: Combine — single-threaded (small result)
    return pl.concat(transformed)


async def main() -> None:
    paths = [Path(f"data/part-{i}.parquet") for i in range(10)]
    result = await process_parquet_files(paths)
    print(f"Processed {len(result)} rows")


if __name__ == "__main__":
    asyncio.run(main())
```

## Dependency Compatibility

Before adopting a free-threaded build, verify every dependency is compatible.

### 1. Check interpreter flag

```bash
python -c "import sysconfig; print('Free-threaded:', bool(sysconfig.get_config_var('Py_GIL_DISABLED')))"
# Free-threaded: 1
# Standard: 0 or None
```

### 2. Check wheel ABI tags

Free-threaded builds require wheels tagged `cp314t` (or `abi3t` for stable ABI). Check your dependencies:

```bash
# List available wheels for a package on free-threaded Python
uv pip index versions polars --python 3.14t

# Or check manually on PyPI: https://pypi.org/project/<package>/#files
# Look for: cp314t-cp314t-manylinux_... or abi3t
```

**Common ecosystem status (2026)**:

| Package | Free-threaded wheel (`cp314t`)? | Notes |
|---------|--------------------------------|-------|
| `polars` | ✅ Yes (since 1.10) | Releases GIL; works on both builds |
| `numpy` | ✅ Yes (since 2.0) | Requires `np.set_num_threads(1)` for deterministic threading |
| `pyarrow` | ✅ Yes (since 16.0) | |
| `pydantic` | ✅ Yes (pure Python + `cp314t` wheels) | |
| `orjson` | ✅ Yes (since 3.10) | Rust extension, free-threaded compatible |
| `httpx` | ✅ Yes (pure Python) | |
| `aiobotocore` | ✅ Yes (pure Python) | |
| `uvloop` | ✅ Yes (since 0.21) | |
| `structlog` | ✅ Yes (pure Python) | |
| `cachebox` | ✅ Yes (pure Python) | |
| `pandas` | ⚠️ Partial | Some wheels; test thoroughly |
| `delta-rs` / `deltalake` | ❌ No | Build from source or use `run_in_thread()` |
| `boto3` / `botocore` | ✅ Yes (pure Python) | |

### 3. C-extension compatibility checklist

For each C-extension dependency:

1. **Check PyPI** for `cp314t` or `abi3t` wheels
2. **If no wheel**: Can you build from source? (`pip install --no-binary <pkg>`)
3. **If builds fail**: Extension uses GIL-dependent APIs → **cannot use free-threaded**
4. **Workaround**: Keep that dependency on `run_in_thread()` with a GIL-enabled interpreter (separate process/container)

```bash
# Test install in isolated environment
uv venv --python 3.14t .venv-ft
source .venv-ft/bin/activate
uv pip install -r requirements.txt
# If any package fails, it's not free-threaded compatible
```

### 4. Runtime verification tests

Add a CI gate that runs your test suite on both builds:

```toml
# prek.toml example
[[repos]]
repo = "local"
hooks = [
  { id = "test-gil", name = "🧪 Tests (GIL)", entry = "uv run --python 3.14 pytest -x -q", language = "system", language_version = "3.14" },
  { id = "test-freethreaded", name = "🧪 Tests (free-threaded)", entry = "uv run --python 3.14t pytest -x -q", language = "system", language_version = "3.14t" },
]
```

**Critical test categories**:

| Test type | Why it matters on free-threaded |
|-----------|---------------------------------|
| **Concurrency stress** | Run thread-heavy tests under `-n auto` (pytest-xdist) to expose races |
| **Shared state mutation** | Tests that mutate globals, class attributes, module-level caches |
| **Lazy initialization** | Singletons, `@lru_cache`, module-level `if not _CACHE: _CACHE = ...` |
| **C-extension interaction** | Any test calling Polars, NumPy, PyArrow — verify no segfaults |

### 5. CI gate: enforce compatibility in `prek.toml`

```toml
# prek.toml — require free-threaded compatibility for new C-extension deps
[tool.prek]
# Custom hook to scan requirements for free-threaded wheel availability
# (implement as a small script; see enforcement.md for checker patterns)
hooks = [
  { id = "check-freethreaded-wheels", name = "🔍 Free-threaded wheel check", entry = "python scripts/check_freethreaded_wheels.py requirements.txt", language = "system", language_version = "3.14" },
]
```

Example checker script:

```python
# scripts/check_freethreaded_wheels.py
"""Fail if a C-extension dependency lacks a free-threaded wheel."""
import subprocess
import sys
import tomllib
from pathlib import Path


C_EXTENSION_PACKAGES = {
    "polars", "numpy", "pyarrow", "orjson", "uvloop",
    "pandas", "deltalake", "delta-rs", "lxml", "cryptography",
}


def has_freethreaded_wheel(pkg: str) -> bool:
    """Check PyPI for cp314t or abi3t wheel."""
    result = subprocess.run(
        ["uv", "pip", "index", "versions", pkg, "--python", "3.14t"],
        capture_output=True,
        text=True,
    )
    return "cp314t" in result.stdout or "abi3t" in result.stdout


def main() -> int:
    req_file = Path(sys.argv[1])
    content = req_file.read_text()

    missing: list[str] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pkg = line.split("==")[0].split(">=")[0].split("<=")[0].strip()
        if pkg.lower() in C_EXTENSION_PACKAGES:
            if not has_freethreaded_wheel(pkg):
                missing.append(pkg)

    if missing:
        print(f"❌ Missing free-threaded wheels: {', '.join(missing)}")
        print("   Options: (1) wait for upstream, (2) build from source, (3) use run_in_thread()")
        return 1

    print("✅ All C-extension dependencies have free-threaded wheels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## Platform Limitations

| Platform | Free-threaded Python 3.14 support |
|----------|-----------------------------------|
| **AWS Lambda** | ❌ Not available — only GIL-enabled runtimes |
| **AWS ECS/EKS** | ✅ Yes — bring your own container with `python:3.14t` base image |
| **Google Cloud Run** | ✅ Yes — custom container |
| **Azure Container Apps** | ✅ Yes — custom container |
| **Kubernetes (self-managed)** | ✅ Yes — `python:3.14t-slim` or custom build |
| **Traditional VMs** | ✅ Yes — compile from source or use `uv python install 3.14t` |

**Implication**: All guidance in this reference applies to **ECS/VM/container workloads only**. Lambda handlers must remain on the GIL-enabled baseline and continue using `run_in_thread()` / `InterpreterPoolExecutor` for CPU parallelism.

## Integration with Skill Conventions

| Convention | Free-threaded impact |
|------------|---------------------|
| **`run_in_thread()`** | Still the **single owner** of thread-offload seam. Use it for C extensions, file I/O, blocking calls — works identically on both builds. |
| **`InterpreterPoolExecutor`** | Remains approved for CPU-bound pure Python on **GIL-enabled** builds. On free-threaded, prefer `ThreadPoolExecutor` (lower overhead, shared memory). |
| **Banned APIs** | `asyncio.to_thread`, raw `ThreadPoolExecutor` outside `thread_pool.py` still banned — free-threading doesn't change ownership rules. |
| **Immutable parameter types** | `Mapping`/`Sequence` for params — **more critical** on free-threaded; mutable shared state is a race. |
| **Pydantic models at boundaries** | Unchanged — validation at boundaries prevents corrupted shared state from propagating. |
| **Docstrings 100%** | Unchanged — `interrogate` runs on both builds. |

## Known Limitations & Follow-up Work

- **Free-threaded builds not universally packaged** — production adoption depends on platform/container image availability. Track [CPython free-threading status](https://github.com/python/cpython/issues/128020).
- **C-extension ecosystem still maturing** — this reference provides compatibility checks but cannot guarantee third-party wheels. Test each dependency.
- **AWS Lambda limitation** — guidance here is for ECS/VM workloads only. Lambda code paths must remain compatible with GIL-enabled builds.
- **Shared mutable state remains a footgun** — free-threading **exposes** races rather than fixing them. The guide reinforces locking discipline and immutable patterns.
- **Debugging tooling** — ThreadSanitizer (TSan) support for free-threaded CPython is emerging; invest in concurrency stress tests.
- **Performance profiling** — `py-spy`, `pyinstrument` work on free-threaded; verify flame graphs show true parallelism (not GIL serialization).

## Cross-references

- [`async-patterns.md`](async-patterns.md) — `run_in_thread()`, `InterpreterPoolExecutor`, semaphore patterns, thread pool ownership
- [`enforcement.md`](enforcement.md) — checker patterns for dependency gates, CI integration
- [`type-hints.md`](type-hints.md) — generics, `ParamSpec` for thread pool callables
- [`error-handling.md`](error-handling.md) — exception handling across thread boundaries
