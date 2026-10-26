# Free-threaded Python 3.14t (opt-in)

**Scope.** This reference does not move the baseline. The floor stays **Python 3.12+**
(see `SKILL.md`, Core principles). Free-threading is an **opt-in** build for specific
workloads. The **GIL-enabled CPython build remains the default** for every project,
every CI matrix entry and every Lambda runtime unless a project explicitly opts in.

Official support status for the free-threaded build (PEP 779) must be verified against
the Python 3.14 release notes and the "What's New" page for the Python version you
target before you rely on it. This reference does not assert that status.

## When to use it

Use the free-threaded build only when **all** of these hold:

- The hot path is **CPU-bound pure-Python code** (parsing, scoring, transformation
  loops) that runs on **threads** inside one process.
- The GIL is measurably the bottleneck (profile first; wall-clock on the GIL build
  does not scale with thread count).
- Every dependency on that path has a `cp314t` wheel or is pure Python (see the
  compatibility check below).

Do **not** use it for:

- **C-extension work.** Polars, DeltaTable and other compiled libraries already
  release the GIL inside their native code. `run_in_thread()` already gives them
  parallelism on the GIL build. Free-threading adds nothing there.
- **Blocking I/O** (file, network). Threads already overlap I/O on the GIL build.
- **Async-first request paths.** Use `async def` and `TaskGroup`, not more threads.
- **Work that needs process isolation** (untrusted code, per-tenant memory isolation).
  Use `ProcessPoolExecutor`, or the subinterpreter option in
  [`async-patterns.md`](async-patterns.md#interpreterpoolexecutor), which is gated on a
  3.14 floor.

## Pros and cons

| Pros | Cons |
| ---- | ---- |
| CPU-bound pure-Python threads can run in parallel on multiple cores. | **Single-thread slowdown** on the free-threaded build compared with the GIL build; benchmark your own workload. |
| No pickling or process spawn cost compared with `ProcessPoolExecutor`. | **Higher memory use** per process than the GIL build. |
| Shared in-process state stays shared (no serialisation of inputs and outputs). | **Shared state is now genuinely concurrent.** Races that the GIL hid will surface. Locks and thread-safety rules become mandatory, not theoretical. |
| Same `threading` and `concurrent.futures` API. | **Wheel availability.** Any dependency without a `cp314t` wheel forces a source build or blocks the install. |
| | **C-extension ABI and global-state risk.** Extensions that assume the GIL may crash or corrupt data. |

## How to implement it

1. **Install the free-threaded interpreter through uv.** Pin it explicitly in the
   project, do not change `requires-python` (it stays `>=3.12`):

   ```bash
   uv python install 3.14t
   uv venv --python 3.14t .venv-ft
   ```

   Keep this as a separate CI job or matrix entry. The default job stays on the GIL
   build.

2. **Keep the owner-wrapper rule.** `run_in_thread()` and the `ThreadPool` owner
   wrapper stay the **only** entry point for threads in application code. Free-threaded
   threads run through the same wrapper. Do not add raw `ThreadPoolExecutor`,
   `threading.Thread` or `asyncio.to_thread` call sites to "take advantage" of the
   free-threaded build. The thread-subprocess guard and its ruff `banned-api` rule
   still apply unchanged. Changing that policy is a separate decision and is out of
   scope for this reference.

3. **Size the pool from Settings.** The worker count comes from the same `Settings`
   value that sizes the owner pool (see [`config.md`](config.md)). No hardcoded
   `max_workers` at module or class level.

4. **Follow the process-global and thread-safety rules.** Under free-threading,
   module-level and class-level mutable state is shared across real parallel threads.
   Apply [`enforcement.md`](enforcement.md) (`process_globals` checker) and
   [`external-system-ownership.md`](external-system-ownership.md). Guard every shared
   mutable object with a lock or make it immutable. Cache objects must be thread-safe
   for concurrent access.

5. **Check the runtime at startup, in tests only.** Confirm the interpreter you think
   you are running really is free-threaded and the GIL is off:

   ```python
   import sys
   import sysconfig

   import pytest

   FREE_THREADED_BUILD = sysconfig.get_config_var("Py_GIL_DISABLED") == 1


   @pytest.mark.skipif(not FREE_THREADED_BUILD, reason="GIL-enabled build")
   def test_runs_free_threaded() -> None:
       assert not sys._is_gil_enabled()
   ```

   Test the build, not the version: a default 3.14 build is also 3.14 but keeps the
   GIL, so a version check alone would fail there. `sys._is_gil_enabled()` exists on
   3.13+ builds only. Use this in a test or a CI-only smoke test. Do not branch
   production behaviour on it.

## How to check dependency compatibility (manual procedure)

This is a documentation procedure. No checker ships with it.

1. **List the runtime dependencies** from `pyproject.toml` and the lock file
   (`uv.lock`).
2. **Look for `cp314t` wheel tags.** For each package, open its PyPI release page
   (or the project's release files) and look for a wheel whose tag contains `cp314t`
   (for example `cp314-cp314t-manylinux_2_17_x86_64.whl`). Pure-Python wheels
   (`py3-none-any`) also work on the free-threaded build.
3. **Cross-check with uv.** Resolve under the free-threaded interpreter and read the
   output; a missing wheel shows up as a source build attempt or a resolution failure:

   ```bash
   uv lock --python 3.14t
   uv sync --python 3.14t --locked
   ```

4. **Run the test suite under the free-threaded interpreter**, including the
   thread-leak and concurrency tests:

   ```bash
   uv run --python 3.14t pytest -n auto
   ```

5. **Treat any dependency without a `cp314t` wheel (and not pure Python) as a
   blocker.** Do not switch to the free-threaded build with that dependency in place.
   Either wait for a release, pin a version that ships the wheel, or keep that workload
   on the GIL build.

Record the result (interpreter, dependency list, test outcome) in the PR description.

## Example placeholders

Use generic names only in examples, for instance `myapp.core.thread_pool` and
`myapp-cpu-worker`. Do not use real project or company names.
