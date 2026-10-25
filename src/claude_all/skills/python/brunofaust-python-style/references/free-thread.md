# Python 3.14 Free-Threaded Build — Full Reference

> Reference page for the `brunofaust-python-style` skill. Covers Python 3.14's free-threaded build (PEP 703), when to use it, pros and cons, how to implement it, and how to check dependency compatibility.

## When to Use

Use a **free-threaded Python 3.14 build** (built with `--enable-free-threading` or `PYTHON_FREE_THREADING=1`) when:

- Your codebase is **CPU-bound** and does not rely on the GIL for correctness
- You want **true parallelism** across multiple cores without the overhead of `ProcessPoolExecutor`
- You are using libraries that **release the GIL** (C extensions built with `Py_LIMITED_API` or `Py_GIL_DISABLED`)
- You want to avoid the process-spawning cost of `ProcessPoolExecutor` for embarrassingly parallel workloads
- You are already targeting Python 3.14 as your baseline (see `references/pyproject-toml.md`)

**Do not use** free-threaded Python when:

- Your code depends on the GIL for thread safety (mixed threading + Python objects without proper synchronization)
- You are using third-party C extensions that are **not** free-threaded compatible and hold the GIL
- You need deterministic debugging with `sys.set_trace()` — free-threaded builds can have different timing behavior
- You are on Python < 3.14 (the free-threaded build is a 3.14+ feature)

## Core Concepts

### Free-Threaded Build (PEP 703)

Python 3.14 introduces an optional **free-threaded build** where the GIL is disabled by default. This is compiled with `--enable-free-threading` at build time, or activated via the `PYTHON_FREE_THREADING=1` environment variable.

Key differences from the default (GIL) build:

| Aspect                     | GIL Build (default)               | Free-Threaded Build               |
| -------------------------- | --------------------------------- | --------------------------------- |
| GIL                        | Always present, single-threaded   | Disabled by default               |
| Parallelism                | Only via `multiprocessing` or `ProcessPoolExecutor` | Native multi-threaded parallelism |
| C extension compatibility  | Universal                         | Requires GIL-release or recompilation |
| Performance for CPU-bound  | Limited by GIL                    | Improved — threads run truly in parallel |
| Overhead                   | Lower (GIL is lightweight)        | Higher (no GIL coordination)      |

### `sys.free_threaded`

In Python 3.14, `sys.free_threaded` is a **read-only boolean** that indicates whether the interpreter was built with free-threading enabled:

```python
import sys

if sys.free_threaded:
    print("Running on a free-threaded Python 3.14 build")
else:
    print("Running on a standard GIL Python build")
```

### `gil_state`

The `gil_state` context manager (new in 3.14) allows explicit GIL control within C extensions and applications:

```python
from _gil import gil_state

# Acquire the GIL (if available in this build)
with gil_state():
    # Code that requires the GIL
    result = some_c_function()

# Release the GIL automatically when exiting the context
```

## Pros and Cons

### Pros

- **True parallelism** — Multiple Python threads can execute CPU-bound code simultaneously on multiple cores
- **Lower overhead** than `ProcessPoolExecutor` — No need to spawn separate processes, serialize/deserialize data via pickle
- **Better for I/O-bound + CPU-bound mixes** — Threads can handle I/O while other threads compute
- **Drop-in replacement** for many codebases — No code changes needed if dependencies are compatible

### Cons

- **Dependency compatibility risk** — Third-party C extensions that hold the GIL will **deadlock** or misbehave
- **No GIL protection** — Race conditions that were previously hidden may surface
- **Debugging complexity** — Non-deterministic behavior, harder to reproduce race conditions
- **C extension ecosystem** — Not all packages are compiled for free-threaded builds yet; some may fall back to GIL-enabled builds or fail to import
- **`sys.set_trace()` and debuggers** — May behave differently; some debugging tools expect the GIL

## How to Implement

### 1. Verify You're on a Free-Threaded Build

```python
import sys

assert sys.free_threaded, "This code requires Python 3.14 free-threaded build"
```

### 2. Update `pyproject.toml` / Project Configuration

If your project targets Python 3.14+ and wants to leverage free-threading, update the `python_version` setting:

```toml
# references/pyproject-toml.md documents this setting
[tool.mypy]
python_version = "3.14"
```

Additionally, if using `uv` to manage the Python environment:

```bash
# Install a free-threaded Python 3.14 build
uv python install 3.14-freethreading
uv python pin 3.14-freethreading

# Or set the environment variable
export PYTHON_FREE_THREADING=1
```

### 3. Check Dependency Compatibility

Not all packages are compatible with free-threaded Python 3.14. To check:

#### a. Check package metadata for GIL-related notes

```bash
pip check  # reports incompatible packages
```

Look for packages tagged with:
- `py-limited-api` — often compatible (uses limited API)
- No `gil` or `free-threaded` markers in `setup.py/pyproject.toml`

#### b. Run a compatibility test

```python
import sys
import importlib

if sys.free_threaded:
    # Check critical dependencies
    deps = ["boto3", "sqlalchemy", "polars", "orjson"]
    for dep in deps:
        try:
            importlib.import_module(dep)
            print(f"✓ {dep} imported successfully")
        except ImportError as e:
            print(f"✗ {dep} import failed: {e}")
```

#### c. Check known compatibility matrices

- Consult each package's issue tracker or README for "Python 3.14 free-threaded" status
- Some packages ship with `PYTHON_GIL` or `free-threading` classifiers in metadata
- Packages using `setuptools` with `py_limited_api` are more likely to be compatible

### 4. Handle Incompatible Dependencies

If a dependency is not free-threaded compatible:

```python
import sys
import warnings

if sys.free_threaded:
    warnings.warn(
        f"{dependency_name} may not be fully compatible with "
        "free-threaded Python. Consider pinning to a GIL build.",
        UserWarning,
    )
```

Or switch to a GIL-build Python interpreter for parts of the codebase that depend on incompatible libraries.

## Checking if Dependencies Are Compatible

### Method 1: `pip check`

```bash
pip check
```

Look for warnings like:

```
Some packages are not compatible with the current Python interpreter:
- package-name: marker; python_version>="3.14" or platform_tag ...
```

### Method 2: Import Test

```python
import sys

def check_dependency_compatibility(package_name: str) -> bool:
    """Check if a package can be imported on this Python build."""
    try:
        __import__(package_name)
        return True
    except ImportError:
        return False

if sys.free_threaded:
    critical_deps = ["boto3", "polars", "orjson"]
    for dep in critical_deps:
        compatible = check_dependency_compatibility(dep)
        print(f"{dep}: {'compatible' if compatible else 'NOT compatible'}")
```

### Method 3: Check Package Metadata

```bash
pip show package-name
```

Look for relevant fields:

```
Metadata-Version: 2.3
Classifier: Programming Language :: Python :: 3
Classifier: Programming Language :: Python :: 3.14
```

Some packages explicitly declare free-threaded compatibility via classifiers or `requires-python`.

### Method 4: Test with `python -X free-threaded`

If you have a standard Python 3.14 build and want to test compatibility:

```bash
python -X free-threaded -m pytest tests/
```

Watch for crashes, import errors, or GIL-related deadlocks.

### Method 5: Consult the Ecosystem Status

Check these resources for up-to-date compatibility information:

- **Python 3.14 release notes** — known compatible/incompatible packages
- **Package maintainers' blogs** — announcements about free-threaded builds
- **GitHub Issues** — search `free-threaded` or `PEP 703` in relevant repos
- **Conditional dependencies** in `pyproject.toml` — some projects use markers like `; python_free_threaded == true`
