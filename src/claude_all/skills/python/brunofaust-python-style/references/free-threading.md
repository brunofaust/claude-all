# Free-threaded Python 3.14 (opt-in build)

**Status: opt-in.** The baseline stays **Python 3.12+** (`SKILL.md` core principle 1, `pyproject.toml` `requires-python`). Free-threaded builds (`3.14t`) are an additional interpreter a project may choose to test and run. Nothing in the default rules changes because a `3.14t` build exists.

## What it is

A free-threaded CPython build runs without the Global Interpreter Lock (GIL). Threads can execute Python bytecode in parallel on separate cores. The standard build (`3.14`) keeps the GIL.

Consequences that matter for this skill:

- Code that relied on the GIL for implicit atomicity (for example, `dict`/`list` operations or read-modify-write on a shared object being "safe" by accident) is no longer protected by it. Locks are the only guarantee.
- The rules in this skill that already assume explicit locks, a single owned thread pool, and no process-global mutable state are the ones that stay valid. Nothing here relaxes them.

## When to use

Use a `3.14t` build when **all** of these hold:

- The hot path is **CPU-bound pure-Python** work (parsing, math, transformation loops) that is currently serialised by the GIL.
- The work runs in **threads that share state** and cannot be cleanly moved to processes or subinterpreters.
- Every dependency on that path has a verified free-threaded wheel or is pure Python (see *Checking dependency compatibility*).

Do **not** reach for it when:

- The workload is **I/O-bound async** (aiobotocore, httpx, asyncpg). The event loop already overlaps the waiting; free-threading adds nothing.
- The time is spent in **C extensions** that already release the GIL (Polars, DeltaTable/Rust FFI). `run_in_thread()` already gets parallelism there on the standard build.
- The project is **single-threaded** (typical Lambda invocation, one request at a time).
- A dependency on the path has no free-threaded wheel and no verified support.

## Pros and cons

| Pros | Cons |
| ---- | ---- |
| Real thread parallelism for pure-Python CPU work, without pickling arguments | Loss of GIL-based implicit atomicity: unlocked shared mutation becomes a data race |
| Shared in-memory state is usable from threads (no IPC) | Dependency risk: any C extension without a `cp314t` wheel blocks the build |
| Same source code runs on both builds | Some single-threaded code may get slower (per-object locking overhead); measure before adopting |
| Lower overhead than process pools for shared-state work | Less mature tooling and fewer third-party tests run under it than the standard build |

### The cost of losing GIL atomicity

Under the GIL, a single bytecode-level operation on a built-in container was effectively atomic. Under free-threading it is not guaranteed. Therefore on a `3.14t` build:

- Every shared mutable object touched by more than one thread needs an explicit lock, or must be replaced by an immutable value plus an atomic swap of the reference.
- "It works in tests" is not evidence. Race conditions appear under load. Run the concurrency tests under the free-threaded build with the GIL disabled.

## How to implement

### 1. Install and run a 3.14t interpreter

Use `uv` to manage the interpreter (the skill's package manager):

```bash
uv python install 3.14t
UV_PROJECT_ENVIRONMENT=.venv-ft uv sync --python 3.14t
```

Run the test suite under it, against the same environment:

```bash
UV_PROJECT_ENVIRONMENT=.venv-ft uv run --python 3.14t pytest
```

### 2. Keep it an opt-in CI / test matrix leg

Add the free-threaded interpreter as a **separate matrix leg** next to the standard 3.12+ leg. Do not replace the default leg. The leg is allowed to be required only once the project's own dependencies pass on it (see the checking procedure below).

### 3. Confirm the GIL state at runtime

Assert the build and GIL state in a test or startup check instead of assuming it:

```python
import sys
import sysconfig


def is_free_threaded_build() -> bool:
    """True when the interpreter was compiled with free-threading support."""
    return bool(sysconfig.get_config_var("Py_GIL_DISABLED"))


def gil_enabled() -> bool:
    """True when the GIL is active at runtime; 3.12 has no probe and always has the GIL."""
    probe = getattr(sys, "_is_gil_enabled", None)  # added in 3.13; absent on the 3.12 baseline
    return True if probe is None else bool(probe())
```

`PYTHON_GIL=0` can disable the GIL on a free-threaded build; the runtime check above shows whether it took effect. A test that expects the GIL to be off must fail if `gil_enabled()` is still `True`.

### 4. Keep the existing concurrency rules as written

These rules are **not relaxed** for free-threaded builds. Each keeps its text; the free-threading note below is an annotation, not a change in the rule.

- **Single owned thread pool.** Blocking work still goes through `run_in_thread()` (`references/async-patterns.md`). Free-threading does not make an unbounded pool acceptable.
  > Free-threading note: more threads now truly run in parallel, so the pool size from `Settings` matters more, not less.
- **No raw `asyncio.to_thread` or `ThreadPoolExecutor`.** The ruff `banned-api` and the `python-thread-subprocess-guard` hook keep enforcing this on every build.
  > Free-threading note: the guard is unchanged. Do not relax it for `3.14t` builds.
- **Lock-guarded lazy singletons** (`unlocked_singleton` rule). A lazy singleton built without a lock is a race on the standard build too, but the GIL often hid it. Keep the lock.
  > Free-threading note: the lock is now the only protection. It is required on every build.
- **Process-memory tenant rules** (`references/tenant-isolation.md`). A process-global cache keyed by tenant is still forbidden. Free-threading does not make shared tenant state safer; it makes concurrent leaks more likely.
  > Free-threading note: unchanged. Tenant-bound state stays per invocation.

## Checking dependency compatibility

This is a procedure the reader runs. The repository does not record upstream wheel status, so no compatibility matrix is shipped here.

1. **Look for `cp314t` wheels in the lock file.** Search `uv.lock` for `cp314t`. A dependency with only `cp314` wheels and no `cp314t` wheel and no sdist fallback will not install on `3.14t` without a source build.
2. **Resolve and install binary-only under 3.14t.** Use a binary-only resolution so a missing wheel fails loudly instead of compiling from source:
   ```bash
   uv sync --python 3.14t --no-build
   ```
   Any package named in the error is a blocker for that dependency.
3. **Run the test suite with the GIL disabled.** Run the full suite under `3.14t` with `PYTHON_GIL=0` and confirm `gil_enabled()` is `False` in the run. Any failure that disappears under the standard build is a likely shared-state race, not a flake.
4. **Check each upstream issue tracker.** For every dependency on the hot path, open its issue tracker or release notes and confirm free-threading support is stated for the version you pin. A passing install is not sufficient; a release note stating support is the evidence to record.

Preferred libraries from `SKILL.md` to check with this procedure (names only; their status is **not verified** here): Polars, orjson, cachebox, pydantic, uvloop, aiobotocore, structlog, PyJWT, xxhash, anyio. Do not record a library as compatible without running steps 1–4 for the version you ship.

## Runtime scope

- **Lambda — unverified.** The skill's Lambda pattern (`lambda_handler` calling `uvloop.run(main(event))`, see `SKILL.md` "Lambda handlers") has **not been verified** for free-threaded builds. Whether the Lambda runtime offers a `3.14t` interpreter, and whether `uvloop` and the rest of the dependency set install on it, is not stated in this repository. Confirm against the current AWS Lambda runtime documentation before using a free-threaded build for any handler. Until confirmed, keep Lambda on the standard build.
- **ECS / containers — the case to evaluate.** A container image built from a `3.14t` base lets the project control the interpreter. This is the target to evaluate first, using the procedure above and the runtime GIL check in the test suite.
- **Single-threaded handlers** gain nothing; keep them on the standard build regardless of runtime.

No claim in this file is sourced from a live check of wheel availability. Each dependency and runtime must be verified with the procedure before it is relied on.
