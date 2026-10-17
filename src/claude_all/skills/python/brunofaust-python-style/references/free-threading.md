# Free-threaded Python 3.14 (3.14t) — opt-in reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Status and scope

- The skill's baseline stays **Python 3.12+**. Free-threading is an **opt-in choice** for a project that already runs (or deliberately chooses to run) a free-threaded 3.14 build (`3.14t`). Nothing in this file raises the floor.
- The default build (`3.14`, GIL enabled) remains the supported target. Code must run unchanged on both builds.
- Free-threaded builds are officially supported as of Python 3.14 (PEP 779), but a package may still lack a `cp314t` wheel. Check dependencies before adopting it (see *Dependency compatibility*).

## When to use it

Use `3.14t` when **all** of these hold:

- The workload is CPU-bound pure-Python work running on threads (parsing, scoring, transformation loops) that is currently serialised by the GIL.
- The shared state is either immutable or protected by explicit locks, and the team can reason about it.
- Every hard dependency has a `cp314t` wheel, or is pure Python.
- Measurements show a real gain on this workload (see *Verify*).

Stay on the GIL build when:

- The work is I/O-bound. The async event loop plus `run_in_thread()` already overlaps waiting; the GIL is rarely the bottleneck.
- The hot path is a C extension that already releases the GIL (Polars, DeltaTable). Free-threading adds little there.
- Any critical dependency is missing a `cp314t` wheel and has no maintained alternative.
- The codebase has unexamined shared mutable state (module-level caches, singletons, `global` counters). Those become real data races without the GIL.

Subinterpreters (`InterpreterPoolExecutor`, see `async-patterns.md`) are a separate option for CPU-bound work that does not need shared mutable state. Compare both before choosing.

## Pros and cons

| Aspect | Pros | Cons |
| --- | --- | --- |
| CPU parallelism | Threads run Python bytecode in parallel on multiple cores | Only helps CPU-bound pure-Python code |
| Overhead | No pickling, no process spawn; shared memory | Single-threaded performance is typically a few percent slower than the GIL build |
| Concurrency model | Keeps the existing `ThreadPoolExecutor` / `run_in_thread` model | Races that the GIL used to hide now surface; code review must check shared state |
| Ecosystem | Growing `cp314t` wheel coverage | Some C extensions still lack `cp314t` wheels or are not yet thread-safe |
| Operations | Same interpreter, same deployment shape | Build variant, wheel tags and lock files differ from the GIL build; CI needs a matching job |
| Testing | Concurrency bugs become reproducible under load | Tests that passed under the GIL may fail intermittently; flakiness needs a root-cause fix, not a retry |

## How to implement it

### 1. Install the free-threaded interpreter

With uv (preferred, matches the skill's *Dependencies = uv* rule):

```bash
uv python install 3.14t
uv venv --python 3.14t .venv
uv sync --locked --python 3.14t
```

Without uv, use the `python3.14t` binary from the python.org or distribution build. Do not use `pip` directly on a project that uses uv; use `uv pip` with `--python 3.14t` if you need an ad-hoc install.

### 2. Pin it in the project

Declare the interpreter for the project without raising the 3.12 floor for everyone else. If the project is 3.14t-only, set `requires-python` to `>=3.14` and document that the free-threaded build is required. If the project supports both builds, keep `requires-python = ">=3.12"` and add the free-threaded interpreter only to CI and to the developer setup for the workload that needs it. See `pyproject-toml.md` for the base configuration.

### 3. Verify the GIL is really off at runtime

Do not assume the flag is off because the binary is `3.14t`. The GIL can be re-enabled at runtime (for example by an incompatible extension module, or by `PYTHONGIL=1`). Check at startup of anything that depends on parallelism:

```python
import sys
import sysconfig


def free_threaded_build() -> bool:
    """True when the interpreter was compiled with free-threading support."""
    return bool(sysconfig.get_config_var("Py_GIL_DISABLED"))


def gil_enabled() -> bool:
    """True when the GIL is active at runtime. Pre-3.13 builds always have the GIL."""
    if sys.version_info < (3, 13):
        return True
    return sys._is_gil_enabled()  # noqa: SLF001 — documented 3.13+ introspection API
```

Rules for using these checks:

- `sysconfig.get_config_var("Py_GIL_DISABLED")` answers "was this build made free-threaded". `sys._is_gil_enabled()` answers "is the GIL active right now". A parallel workload should require both to say *free-threaded build and GIL off*.
- If the check fails, log a structured warning with the actual state and fall back to the normal code path. Do not silently continue assuming parallel speed-ups.
- Keep the check in one module (the settings or runtime bootstrap owner), not scattered across call sites.
- `PYTHONGIL=0` asks for the GIL to stay off. `PYTHONGIL=1` forces it on. Environment access still goes through `Settings` in this skill, so read the value there if the project needs it; do not call `os.getenv()` from business code.

### 4. Keep the threading model, change only the shared state

The skill's threading guidance does not change:

- Blocking work still goes through the single owned pool, `run_in_thread()`, sized from settings. Do not introduce a second pool and do not call `asyncio.to_thread()` directly. See `async-patterns.md` (*Running Blocking Code in Threads*).
- Direct `ThreadPoolExecutor` use stays subject to the same rules as on the GIL build (the banned-api hook still applies). Free-threading is not a reason to add ad-hoc executors.

What does change is the review of **shared mutable state**:

- Module-level dicts, lists and caches that are written from more than one thread need a lock, or must become immutable values built once.
- Prefer passing context objects over globals (see the *Global mutable state* quick rule in SKILL.md).
- `cachebox` caches are shared by design; confirm the chosen cache is safe for concurrent writers on `3.14t` before relying on it from multiple threads.
- Check-then-act sequences (`if key not in d: d[key] = ...`) are not atomic, even though they were often "fine" under the GIL. Use a lock, `setdefault`, or a single owner.
- Do not rely on the GIL for atomicity of compound operations, `list.append` ordering, or dict iteration while another thread mutates the dict.

### 5. Test under real threads

- Run the concurrency-sensitive tests on the `3.14t` interpreter in CI, not only on the GIL build.
- Use `concurrent.futures` or `run_in_thread()` with enough parallel calls to surface races. A single-threaded test cannot prove thread safety.
- A test that fails only under `3.14t` is a real race until proven otherwise. Fix the shared state; do not add a retry or a `xdist_group`-style workaround.

## Dependency compatibility

Run this procedure for every direct and transitive dependency before adopting `3.14t`. It is concrete and checkable.

### Step A — list the dependencies

```bash
uv export --locked --format requirements-txt --no-hashes > tmp/requirements.txt
```

Use the lock file, not the declared ranges, so transitive packages are included. Keep the output under `tmp/` (never committed).

### Step B — check for `cp314t` wheels on PyPI

For each package, open its PyPI release page for the version pinned in the lock file and look at the wheel filenames. A free-threaded wheel has the ABI tag `cp314t`, for example `pkg-1.2.3-cp314-cp314t-manylinux_2_17_x86_64.whl`. Also accept `abi3`-free `py3-none-any` wheels for pure-Python packages.

Decision per package:

| Finding | Action |
| --- | --- |
| `py3-none-any` wheel (pure Python) | Compatible |
| `cp314t` wheel for each platform you deploy to | Compatible |
| Only `cp314` (GIL) wheels, or sdist only that needs a C compiler | Not compatible yet; find a newer release, an alternative, or keep the GIL build |
| No wheel for a platform you deploy to | Not compatible on that platform |

### Step C — let the resolver confirm it

Resolve against the free-threaded interpreter so the lock is produced for `3.14t`:

```bash
uv lock --python 3.14t
uv sync --locked --python 3.14t
```

A resolution or build failure here is the authoritative answer. If `uv` has to build an sdist from source for a package that has no `cp314t` wheel, treat that package as not compatible until its build is verified on the free-threaded build.

### Step D — check the runtime

Run the test suite on `3.14t` and confirm the GIL state with the checks in *Verify the GIL is really off*:

```bash
uv run --python 3.14t python -c "import sys, sysconfig; print(sysconfig.get_config_var('Py_GIL_DISABLED'), sys._is_gil_enabled())"
```

Expected output for a healthy free-threaded run: `1 False`. Output `1 True` means a loaded module re-enabled the GIL. Find it by setting `PYTHONGIL=0` and reading the warning the interpreter prints at import time, then replace or pin that module.

### Step E — record the result

Write the outcome (date, interpreter, packages without `cp314t` wheels, and the GIL state) in the project's `ARCHITECTURE.md` or the decision record the project already uses. Re-run Steps B–D on every dependency upgrade, because a new release can drop or add a `cp314t` wheel.

## Verify the benefit

Free-threading only pays off when a measurement says so. Before and after switching the workload:

- Time the same CPU-bound workload with a fixed input on the GIL build and on `3.14t`, using the same number of threads.
- Compare throughput per core as well as wall time; a gain that only appears with many more cores is a capacity change, not a speed-up.
- Keep the result with the decision record. If the gain is below the cost of the extra CI job and the locking review, stay on the GIL build.

## Known limitations

- Free-threaded builds are slower per thread than the GIL build in some workloads and may use more memory.
- Some C extensions re-enable the GIL when imported. The runtime check above is the only reliable detector.
- This file does not cover subinterpreters or process pools in depth; see `async-patterns.md`.
- Enforcement is advisory. No checker in the skill flags `cp314t`-incompatible pins or `sys._is_gil_enabled()` usage, so compliance depends on review and the procedure above.
