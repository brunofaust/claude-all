# Free-threaded Python 3.14 (opt-in)

**Status: opt-in.** The skill's baseline stays Python 3.12+ (SKILL.md core principle #1).
Nothing in this file raises the floor. Read it when a project *considers* or *adopts* the
free-threaded build (`3.14t`), or when someone asks whether the dependencies work on it.
A project that keeps the GIL build on 3.12/3.13/3.14 follows the rest of the skill unchanged.

PEP 779 made free-threaded CPython a supported build in 3.14 (PEP 703 was the design).
The GIL-enabled build is still the default interpreter.

## When to use it

Use the `3.14t` build only when all of these hold:

| Signal | Why it matters |
| --- | --- |
| CPU-bound pure-Python work runs on threads and is the measured bottleneck | Threads only run Python bytecode in parallel without the GIL |
| The work shares mutable state across threads that you control | The GIL no longer hides races, so shared state must be already correct |
| Your hot C extensions declare free-threading support (see the dependency check) | A C extension that does not may re-enable the GIL or crash |
| You can run the full test suite on `3.14t` in CI | Race bugs only show up under real parallelism |

Do **not** use it just for blocking I/O. `run_in_thread` only keeps blocking work off the
event loop; the C extensions and OS calls it wraps (Polars, DeltaTable, file I/O) release the
GIL themselves, so the GIL build is simpler there. For CPU-bound pure Python
that needs no shared state, `InterpreterPoolExecutor` (see `async-patterns.md`) is still the
3.14 option.

## Pros and cons

| Pros | Cons |
| --- | --- |
| Real parallel execution of Python threads | Single-threaded code can be slower than the GIL build (overhead is lower in 3.14 but not zero; measure it) |
| No need for `ProcessPoolExecutor` pickling for CPU-bound threads | Ecosystem gaps: some C extensions have no `cp314t` wheel or re-enable the GIL |
| Threads can share large in-process objects without copying | Data races become real: unlocked lazy init, check-then-act, and unsynchronised caches fail in new ways |
| Fits the existing owned thread pool pattern | Debuggers, profilers, and tools may lag behind the build |
| | Must be run and tested as a separate CI target |

## How to implement

### 1. Install the interpreter with uv

```bash
uv python install 3.14t
uv venv --python 3.14t
uv sync --locked
```

Keep the project's `requires-python` at the 3.12 baseline. Do not add `3.14t` as the only
supported interpreter for the whole project unless the project has explicitly chosen to.
If the project does choose it, update `requires-python` and the classifiers in
`pyproject.toml` (see `pyproject-toml.md`) and every `language_version` pin in the checker
and hook configuration in the same change.

Classifiers, if the project publishes them, add the free-threaded marker explicitly:

```toml
classifiers = [
    "Programming Language :: Python :: 3.14",
    "Programming Language :: Python :: Free Threading :: 3 - Stable",
]
```

### 2. Check at runtime which build is running

```python
import sys


def gil_enabled() -> bool:
    """True when the interpreter runs with the GIL (default 3.14 build)."""
    return sys._is_gil_enabled()  # noqa: SLF001 - only public way to query the GIL state
```

`sys._is_gil_enabled()` is the documented check in 3.13+. It returns `False` on a
free-threaded build where the GIL is off. Use it in a startup log line or a test, not as
branching business logic.

Force the GIL off or on at runtime with the environment variable (the value is read at
startup):

```bash
PYTHON_GIL=0 uv run pytest      # request free-threaded execution
PYTHON_GIL=1 uv run pytest      # force the GIL on
```

`PYTHON_GIL=0` is a request, not a guarantee: importing a C extension that does not support
free-threading turns the GIL back on, with a `RuntimeWarning`. Treat that warning as a finding.

### 3. Existing rules still apply, with extra care

- **Owned thread pool and `run_in_thread`** (`async-patterns.md`) stay as the way to move
  blocking work off the event loop. The free-threaded build changes the speed, not the rule
  that the event loop must not block.
- **Shared state** must be synchronised explicitly. Anything that relied on the GIL for
  atomicity (a dict update followed by a read, a lazy singleton created on first use) needs a
  lock or a construction at import time. The `unlocked_singleton.py` checker is already
  enforcing this, and it is more important on `3.14t`. Do not weaken it.
- **Tenant-bound process state** (`tenant-isolation.md`) is unchanged; free-threading makes the
  leak class easier to trigger, not harder.
- **`python-thread-subprocess-guard`** remains valid: subprocess creation from threads is still
  a hazard on both builds.

No checker is added by this reference. Rule changes for the GIL-era thread guidance are a
separate decision.

## Dependency compatibility check (procedural)

There is no inventory in this skill. Run this procedure for each runtime dependency the
project actually uses. The preferred libraries table in `SKILL.md` is the starting list
(Polars, orjson, uvloop, xxhash, aiobotocore, cachebox, structlog, Pydantic, PyJWT); verify
each one yourself at the time of the check. Do not copy a status from this file or from a
previous review.

1. **Find the wheels.** Look on the package's release page or the index for a `cp314t`
   wheel for each platform you deploy to (for example `cp314-cp314t-manylinux_*`). A pure
   Python wheel (`py3-none-any`) is compatible by construction. An sdist-only release that must
   compile means the build toolchain must handle the free-threaded ABI; verify that before
   relying on it.
2. **Read the support statement.** Check the project's README, changelog, or docs for an
   explicit free-threading statement. Absence of a statement counts as unsupported.
3. **Install on 3.14t and check the GIL.** In a clean venv:

   ```bash
   uv venv --python 3.14t /tmp/ft-check
   uv pip install --python /tmp/ft-check <package>
   /tmp/ft-check/bin/python -c "import <module>, sys; print(sys._is_gil_enabled())"
   ```

   `False` means the import left the GIL off. `True` means the package (or something it imports)
   re-enabled the GIL. Record that as a finding, with the package name and version.
4. **Run the suite under the free-threaded build, in parallel.** `PYTHON_GIL=0 uv run pytest -n auto`
   on `3.14t` (`-n` is the pytest-xdist worker count; a serial run cannot expose the races this step
   is for, so use the project's parallel test command if it differs). Any `RuntimeWarning` about the GIL being
   re-enabled, and any failure that does not reproduce on the GIL build, is a finding.
5. **Record the result** in the ticket or PR: interpreter version, each dependency's verdict
   (wheel found / support statement / GIL state / suite result), and the date of the check.

A dependency that fails any step is either replaced, pinned to a version that passes, or kept
out of the free-threaded target. Do not switch the whole project to `3.14t` because one library
fails.

## Anti-patterns

- ❌ Raising the project floor to `3.14t` without an explicit decision and a matching change to
  `requires-python`, classifiers, and checker pins.
- ❌ Assuming a library works on `3.14t` because it works on 3.12.
- ❌ Reading the GIL state to pick between a locked and an unlocked code path.
- ❌ Dropping a lock or the `unlocked_singleton` rule because the build "has no GIL" in local tests.
- ❌ Ignoring the `RuntimeWarning` about the GIL being re-enabled.
