# Python 3.14 Free-Threaded Build — Reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## What Is the Free-Threaded Build?

Python 3.14 introduces a free-threaded build variant (also called "no-GIL" or "nogil"),
compiled with `--disable-gil`. In this build, the global interpreter lock (GIL) is disabled
by default, allowing CPU-bound work to achieve true parallelism across multiple threads
within a single process.

The free-threaded build is available as `python3.14 -m freethread` or via the `python3.14`
executable when compiled with `configure --disable-gil`.

```bash
# Check if running free-threaded Python
python3.14 -c "import sys; print(sys.unix flag, sys.py314.flags)"
# Output will include 'free-threaded' on the free-threaded build
```

## When to Use the Free-Threaded Build

Use the free-threaded build when:

- **CPU-bound parallelism is needed** without the overhead of `multiprocessing`.
  Threads can run in true parallelism, which is ideal for workloads that are
  thread-safe and don't hold the GIL across calls.

- **Mixing async and sync code** where some operations release the GIL naturally
  (e.g., NumPy, Pandas, C extensions that release the GIL during computation).

- **Reducing process count** — a single process with multiple threads can replace
  a process pool for certain workloads, reducing memory overhead and process
  startup latency.

- **Existing code is already thread-safe** or can be made thread-safe with minimal
  changes. If code already uses `threading`, `concurrent.futures`, or async I/O
  patterns, the transition is smoother.

**Do not use** the free-threaded build when:

- Code relies on CPython's GIL for thread safety — shared mutable state must be
  protected explicitly (locks, atomic operations, or thread-local storage).

- Third-party C extensions are not free-threaded compatible — many extensions
  assume the GIL is held and may crash or corrupt data when it is absent.

- The codebase uses CPython C API directly — the absence of the GIL changes
  object lifetime and reference counting guarantees.

## Pros and Cons

### Pros

- **True parallelism for CPU-bound work** — multiple threads can execute Python
  bytecode simultaneously, leveraging all available CPU cores within a single process.

- **Lower memory footprint** — one process with multiple threads uses less memory
  than an equivalent `multiprocessing` setup with separate processes.

- **Better integration with async code** — the event loop and threads coexist
  naturally; `run_in_thread()` and `asyncio.to_thread()` benefit from reduced
  contention.

- **Compatibility with existing sync libraries** — libraries like NumPy, Pandas,
  and scikit-learn already release the GIL during computation, so they work
  immediately in the free-threaded build.

### Cons

- **Thread-safety bugs surface** — code that works under the GIL may corrupt
  shared state when the GIL is absent. Existing race conditions become visible.

- **Third-party extension compatibility** — many popular C extensions (e.g.,
  older versions of `psycopg2`, `boto3`, `sqlalchemy`) are not compiled for the
  no-GIL build and may raise `RuntimeError: the GIL is released` or crash.

- **Debugging is harder** — race conditions and non-deterministic behavior are
  more common; traditional debugging techniques may not reproduce issues.

- **Some stdlib modules are affected** — modules that assume the GIL is held
  may misbehave; see the "Dependency compatibility" section below.

## How to Implement the Free-Threaded Build

### 1. Compile or Install Python 3.14 with `--disable-gil`

```bash
# From source
cd /usr/local/src/python-3.14.0
./configure --disable-gil --enable-optimization
make -j$(nproc)
make altinstall  # installs as python3.14, does not replace system python

# Or via uv (if available)
uv pip install python3.14 --extra-index-url https://...
# or use a pre-built free-threaded distribution
```

### 2. Verify the Build Is Free-Threaded

```bash
python3.14 -c "import sys; print(sys.unix flag)"
# On free-threaded build: __pecos__ or similar indicator
# More reliable:
python3.14 -c "
import sys
print('Python version:', sys.version)
print('Free-threaded flag:', 'free-threaded' in sys.version.lower())
"
```

Alternatively, check `sys.py314.flags` — the free-threaded build sets a flag.

### 3. Update `pyproject.toml` or `environment` to Target 3.14

If using tooling like `tox`, `poetry`, or `uv`, set the minimum Python version:

```toml
# pyproject.toml
[tool.poetry]
python = "3.14"

# Or with uv
uv init --python 3.14
```

### 4. Add `from __future__ import annotations` Where Needed

PEP 649 (lazy annotation evaluation) is 3.14-only. If the codebase uses
forward references in type hints, add:

```python
from __future__ import annotations
```

This makes all annotations strings lazily evaluated, which is required for
compatibility with the free-threaded build where annotation evaluation order
can differ.

### 5. Update Type Hints for PEP 695

PEP 695 generics are available in 3.14. You can now use:

```python
from typing import TypeAlias

type PlayerId = str

def find_player(player_id: PlayerId) -> PlayerId:
    ...
```

Or class-based generics:

```python
class Stack:
    def push(self, item: T) -> None: ...
    def pop(self) -> T: ...
```

### 6. PEP 758 — Parenthesised `except` Clauses

PEP 758 allows the parenthesised form on all Python versions, but the
paren-less form `except ValueError, TypeError:` is **3.14-only**:

```python
# 3.14+: either form works
except (ValueError, TypeError):    # recommended, works everywhere
    ...

# 3.12/3.13: must use parenthesised form
except (ValueError, TypeError):    # SyntaxError without parens on 3.12/3.13
    ...
```

### 7. PEP 734 — `InterpreterPoolExecutor`

Available in the free-threaded build, `InterpreterPoolExecutor` provides true
parallelism via sub-interpreters, each with its own GIL. Use this for CPU-bound
work that cannot release the GIL:

```python
from concurrent.futures import InterpreterPoolExecutor

with InterpreterPoolExecutor() as executor:
    results = list(executor.map(compute_heavy, range(1000)))
```

## Checking Dependency Compatibility

This is the most critical step when migrating to the free-threaded build. Not
all third-party packages are compiled for the no-GIL build. Here is a systematic
approach to verify compatibility:

### Step 1: Run the Dependency Import Test

```python
# test_compatibility.py
import sys

def check_package(package_name):
    try:
        __import__(package_name)
        print(f"✓ {package_name} imported successfully")
        return True
    except (ImportError, RuntimeError) as e:
        print(f"✗ {package_name} failed: {e}")
        return False

# Check critical packages
packages = [
    "numpy", "pandas", "pydantic", "sqlalchemy",
    "redis", "aiobotocore", "httpx", "structlog"
]

results = {pkg: check_package(pkg) for pkg in packages}
failed = [pkg for pkg, ok in results.items() if not ok]

if failed:
    print(f"\n⚠ {len(failed)} packages may be incompatible:")
    for pkg in failed:
        print(f"  - {pkg}")
    sys.exit(1)
else:
    print("\n✓ All checked packages import successfully")
    sys.exit(0)
```

### Step 2: Test GIL-Releasing Behavior

For each package, verify it doesn't crash when the GIL is absent:

```python
import sys
import threading

# On free-threaded build, this should work without RuntimeError
def test_gil_release():
    try:
        # NumPy typically releases the GIL during computation
        import numpy as np
        a = np.array([1, 2, 3])
        b = np.array([4, 5, 6])
        _ = np.dot(a, b)
        print("NumPy GIL-release test: PASS")
    except RuntimeError as e:
        if "GIL" in str(e):
            print("NumPy GIL-release test: FAIL -", e)
        else:
            raise

test_gil_release()
```

### Step 3: Concurrency Stress Test

Run the code under load with multiple threads to surface race conditions:

```python
import threading
import time
import sys

shared_value = 0
lock = threading.Lock()  # Proper synchronization

def increment():
    global shared_value
    for _ in range(100000):
        # Without lock: race condition on free-threaded build
        # With lock: safe
        with lock:
            shared_value += 1

threads = [threading.Thread(target=increment) for _ in range(4)]
for t in threads:
    t.start()
for t in threads:
    t.join()

print(f"Final value: {shared_value} (expected: {4 * 100000})")
if shared_value == 400000:
    print("Concurrency test: PASS")
else:
    print("Concurrency test: FAIL - race condition detected")
```

### Step 4: Check Project-Specific Compatibility

For each installed package, consult these resources:

| Package | Compatibility Status | Notes |
|---------|----------------------|-------|
| `numpy` | ✓ Compatible | Releases GIL during computation |
| `pandas` | ✓ Compatible | Releases GIL during operations |
| `pydantic` | ✓ Compatible | No C extensions holding GIL |
| `sqlalchemy` | ✗ May fail | Some C extensions may not be no-GIL |
| `psycopg2` | ✗ Known issue | Version 2.9+ adds no-GIL support; check version |
| `boto3` | ✓ Compatible | Pure Python + botocore; releases GIL as needed |
| `redis` | ✓ Compatible | Pure Python client |

### Step 5: Update Dependency Pinning

When a package is confirmed compatible, ensure it is pinned to a version that
supports the free-threaded build. Some packages require a minimum version:

```toml
# pyproject.toml
[tool.poetry.dependencies]
numpy = ">=1.26"  # 1.26+ adds no-GIL support
pandas = ">=2.1"  # 2.1+ fully supports free-threaded build
```

If a package is not compatible, consider:

- Pinning to a version known to work, or
- Finding an alternative package, or
- Falling back to `multiprocessing` for that dependency

## Migration Checklist

☐ Python 3.14 free-threaded build installed and verified
☐ `pyproject.toml` targets Python 3.14
☐ All critical third-party packages import without errors
☐ GIL-release behavior tested for NumPy/Pandas/etc.
☐ Concurrency stress test passes with proper synchronization
☐ Incompatible packages identified and addressed (pin, replace, or fallback)
☐ `from __future__ import annotations` added where needed (PEP 649)
☐ PEP 695 generics updated if using type aliases
☐ Parenthesised `except` clauses updated for PEP 758 compliance
☐ `InterpreterPoolExecutor` evaluated for CPU-bound work
☐ Documentation updated for the team (this reference file)
☐ Rollback plan: keep 3.12/3.13 available until compatibility is confirmed

## Known Issues and Gotchas

1. **`contextlib.suppress` across threads** — On the free-threaded build,
   `suppress()` may behave differently if the guarded code releases the GIL.
   Prefer explicit `try/except` when thread-safety is involved.

2. **`asyncio` and threads** — `asyncio.to_thread()` works, but if the wrapped
   function acquires the GIL (e.g., via a C extension), you get no parallelism.
   Test with `perf` or thread profiling to confirm.

3. **Logging from multiple threads** — structlog and standard logging are thread-safe,
   but ensure correlated context (contextvars) is properly passed between threads.

4. **Sub-interpreters vs. threads** — `InterpreterPoolExecutor` (PEP 734) gives
   true isolation (each interpreter has its own GIL), but data must be picklable
   between interpreters. Use threads when sharing mutable state, interpreters
   when isolation is preferred.

5. **C extension finalization order** — On the free-threaded build, C extensions
   that hold the GIL during `atexit` finalization may deadlock. Ensure all
   threads are joined before process exit.

## Further Reading

- [PEP 703 – Free-Threaded Python](https://peps.pep-703/) — the definitive spec
- [Python 3.14 Release Notes](https://docs.python.org/3/whatsnew/3.14.html)
- [GIL-free programming patterns](https://docs.python.org/3/gl/gil.html)
- [NumPy GIL release documentation](https://numpy.org/doc/stable/user/basics.gil.html)
- [Pandas and the GIL](https://pandas.pydata.org/docs/user/basics.html#the-gil)
