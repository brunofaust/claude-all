# Python 3.14 Free-Threading — Reference Guide

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Overview

Python 3.14 introduced *free-threaded* (aka "no-GIL") builds via PEP 703 / PEP 684 (subinterpreters already existed). A free-threaded build removes the Global Interpreter Lock, allowing multiple Python threads to execute bytecode in parallel on multiple cores. This is distinct from — and complementary to — the async-first, `run_in_thread` patterns in `async-patterns.md`.

Free-threading does **not** make mutable shared state safe. It exposes race conditions rather than fixing them. It changes the concurrency model: true CPU parallelism for pure-Python code, with stricter expectations around thread safety.

### Relationship to existing skill conventions

* **InterpreterPoolExecutor (PEP 734, Python 3.14+)** — `references/async-patterns.md` already documents `concurrent.futures.InterpreterPoolExecutor` for CPU-bound pure-Python work. InterpPool provides true parallelism via isolated subinterpreters, with picklable arguments/results only.
* **run_in_thread()** — single owner of the thread-offload seam for blocking/C-extension work. Banned-API prek hook blocks raw `asyncio.to_thread` / `ThreadPoolExecutor` usage outside the skill's owner.
* **Free-threading** — removes the GIL within one interpreter, enabling parallel execution of pure-Python bytecode across threads. It is a runtime choice, not a code pattern. When available, it can replace `InterpreterPoolExecutor` for workloads that need shared memory / non-picklable state, provided the code is thread-safe.

Prefer:
* I/O-bound → `async/await` + `run_in_thread()` for blocking calls
* CPU-bound pure-Python, picklable → `InterpreterPoolExecutor` (current skill default)
* CPU-bound pure-Python, shared state required → free-threaded runtime *if* dependencies are compatible and code is thread-safe
* CPU-bound C extensions → `run_in_thread()` (extensions already release GIL)

## When to Use

Free-threading is appropriate when **all** of the following hold:

1. **Python 3.14+ free-threaded build is available** in the target runtime (ECS/VM self-managed; AWS Lambda does **not** ship a free-threaded Python 3.14 runtime at this time — see Platform Limitations).
2. **Workload is CPU-bound pure-Python** where threads would otherwise contend for the GIL.
3. **Dependencies are free-thread compatible** — no C extensions with global mutable state, no libraries relying on GIL semantics.
4. **Code is thread-safe** — no unsynchronised mutation of shared data structures, no reliance on "GIL protects me".
5. **Pickling overhead is undesirable** — `InterpreterPoolExecutor` requires picklable args/results; free-threading avoids that cost.

Do **not** use free-threading to fix blocking I/O, to replace `asyncio`, or as a blanket performance toggle. Async remains the primary concurrency model for I/O.

## Pros and Cons

### Pros

* True parallelism for pure-Python CPU work without process overhead.
* Share memory / objects between workers — no pickling required.
* Lower latency for fine-grained parallelism compared to process pools.
* Complements async: async for I/O, threads for CPU within a free-threaded interpreter.

### Cons

* **No silver bullet for thread safety** — data races, deadlocks, and visibility bugs become possible. Existing code that assumed GIL safety will break.
* C-extension ecosystem is still maturing for free-threading. Many extensions must be rebuilt with `cp314t` tags and verified for thread safety.
* Debugging concurrency bugs is harder; race conditions are non-deterministic.
* Platform support limited: not available on AWS Lambda; requires self-managed runtime (ECS, EKS, EC2/VM).
* Shared mutable state remains unsafe; free-threading does not provide safety, only opportunity.

## Implementation

### Runtime Selection

Enable a free-threaded build at the environment level, not via code flag.

```bash
# Example: uv + free-threaded CPython 3.14
uv python install 3.14 --free-threaded
uv python pin 3.14
```

In `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py314"

[dependency-groups]
dev = ["pytest", "mypy", "ruff"]
```

Interpretation of the flag:

```python
import sys
import sysconfig

def is_free_threaded() -> bool:
    # Python 3.13+ exposes freethreading flag
    return getattr(sys.flags, "freethreading", False)

def interpreter_abi_tag() -> str:
    # Free-threaded wheels use cp314t, standard uses cp314
    return sysconfig.get_platform_tag()
```

### Code Patterns

Free-threading is a runtime property; code changes are only needed for thread safety.

**Thread-safe worker pattern**

```python
import threading
from collections import defaultdict

_lock = threading.Lock()
_shared_counter = defaultdict(int)

def process_item(item: dict) -> None:
    # Guard shared mutation
    with _lock:
        _shared_counter[item["key"]] += 1
```

Avoid global mutable state. Prefer immutable data, thread-local storage, or explicit locks.

**Hybrid async + free-threaded CPU work**

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

class CPUWorker:
    def __init__(self) -> None:
        # In a free-threaded interpreter, threads can run CPU-bound Python in parallel
        self._pool = ThreadPoolExecutor(max_workers=4)

    def compute(self, data: list[int]) -> list[int]:
        # Pure-Python CPU work runs in parallel under free-threading
        with self._pool as pool:
            return list(pool.map(self._heavy_pure_python, data))

    def _heavy_pure_python(self, n: int) -> int:
        # CPU-bound pure Python
        total = 0
        for i in range(n):
            total += i * i
        return total
```

When free-threading is unavailable, the same code still works but threads serialize on GIL.

### Interaction with skill conventions

* Free-threading **does not** replace `run_in_thread()` for blocking C extensions. Extensions that release the GIL are already parallel; free-threading adds no benefit.
* Free-threading **complements** `InterpreterPoolExecutor`. Choose InterpPool for isolated, picklable workloads; free-threading for workloads needing shared memory.
* Banned-API rules for `asyncio.to_thread` and `ThreadPoolExecutor` remain. Use the skill's `run_in_thread()` owner.

## Compatibility Checking

### Interpreter verification

* `sys.flags.freethreading` is `True` on free-threaded builds.
* `sysconfig.get_config_var("Py_GIL_DISABLED")` is `1` on free-threaded builds.

Add a runtime gate:

```python
if not getattr(sys.flags, "freethreading", False):
    raise RuntimeError("Free-threaded interpreter required for this service")
```

### Wheel ABI inspection

Free-threaded wheels use the `cp314t` ABI tag (the `t` suffix denotes "threaded").

```bash
# Inspect installed wheel tags
python -c "import sysconfig; print(sysconfig.get_config_vars('SOABI'))"
pip show some-package --files
```

CI check: ensure no `cp314` non-threaded ABI wheels are installed when a free-threaded interpreter is expected.

### C-extension compatibility checklist

For each dependency:

* Does it ship `cp314t` wheels? If only `cp314`, building from source is required.
* Is the extension GIL-aware / uses `Py_BEGIN_ALLOW_THREADS` correctly?
* Does it use global mutable state, module-level caches, or C-level locks assuming GIL?
* Are there known issues in the project's changelog for free-threading support?

Maintain an allowlist of verified packages. Block untrusted C extensions via `prek.toml` CI gate.

### Runtime verification tests

* Smoke test: run CPU-bound pure-Python workload under threading; measure speedup >1x on multi-core.
* Race detection: run thread-safety torture tests under `threading` with high contention.
* Dependency loading test: import all C extensions in a free-threaded interpreter, fail on `ImportError`.

Example `prek.toml` CI gate:

```toml
[[hooks]]
id = "python-free-thread-check"
name = "Verify free-threaded interpreter"
entry = "python -c \"import sys; exit(0 if getattr(sys.flags,'freethreading',False) else 1)\""
language = "system"
files = "src/.*\\.py$"
```

### Platform / runtime limitations

* **AWS Lambda** does not ship a free-threaded Python 3.14 runtime at time of writing. Guidance is limited to ECS/VM/self-managed runtimes.
* Containers must be built with a free-threaded base image.
* Shared mutable state remains unsafe. Free-threading does not provide safety guarantees.

## Decision Matrix

| Workload | GIL-bound? | Picklable? | Needs shared state? | Recommended |
| --- | --- | --- | --- | --- |
| I/O-bound | No | N/A | No | async + `run_in_thread()` |
| CPU-bound C extension | No (releases GIL) | N/A | No | `run_in_thread()` |
| CPU-bound pure-Python | Yes | Yes | No | `InterpreterPoolExecutor` |
| CPU-bound pure-Python | Yes | No | Yes | Free-threading *if* compatible & thread-safe |
| CPU-bound pure-Python | Yes | Yes | Yes | Free-threading *if* compatible & thread-safe (avoids pickling) |

## Related Documentation

* See `async-patterns.md` for detailed coverage of `InterpreterPoolExecutor` vs `run_in_thread()` usage guidelines
* Refer to `enforcement.md` for banned-api rules regarding threading mechanisms
* Consult `SKILL.md` for high-level skill conventions and recommendations
