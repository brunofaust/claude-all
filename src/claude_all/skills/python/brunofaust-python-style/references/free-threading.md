# Free-threaded CPython (3.14t)

Free-threaded CPython builds (PEP 703) run without the global interpreter lock.
Threads in one process can execute Python bytecode in parallel. This reference
says when to consider it, what it costs, how to run it, and how to check
dependencies. It does **not** change the baseline: the project stays on the
3.12+ baseline with the default (GIL) build. Free-threading is an opt-in tool
for specific workloads.

## When to use

**Default stance: opt-in per workload, never the default.** The default GIL
build stays the default interpreter. Do not switch a service to `3.14t` because
it is "faster"; switch one workload, measured, after the checks below pass.

Free-threading helps only when all of these hold:

- The work is **pure-Python CPU-bound** (parsing, math, transforms, scoring loops).
- Multiple threads must **share state** in one process (a shared in-memory index,
  a large object graph that is expensive to pickle or copy).
- Measurement shows the GIL is the bottleneck (threads do not scale on the GIL build).

It gives **no gain for C-extension work**. Polars, DeltaTable and similar
extensions already release the GIL while they compute, so threads already run in
parallel for them. For those, keep the `run_in_thread` table in
[`async-patterns.md`](async-patterns.md) (`run_in_thread` for C-extension CPU
work and blocking I/O).

For CPU-bound pure Python that does **not** need shared state, the existing
choice in [`async-patterns.md`](async-patterns.md) still applies:
`InterpreterPoolExecutor` (isolation, one GIL per interpreter) or
`ProcessPoolExecutor` on the 3.12 baseline. Free-threading is an alternative for
the shared-state case, not a replacement for the isolation case.

## Pros and cons

**Pros**

- Real parallelism for pure-Python threads that share objects in one process.
- No pickling or copying of shared data between workers.

**Cons**

- **Single-thread slowdown.** Free-threaded builds are typically slower for
  single-threaded code than the GIL build, because of the extra locking. Measure
  the workload on both builds before deciding.
- **More exposure to data races.** Without the GIL, unsynchronised mutation of
  shared containers and module state is no longer incidentally serialised. A
  race that was rare becomes routine.
- **C extensions must be free-thread-safe.** An extension that is not marked
  free-threading compatible can crash or re-enable the GIL. See the dependency
  check below.
- **No isolation.** `InterpreterPoolExecutor` gives each worker its own
  interpreter state; free-threading shares everything. Isolation has to be
  designed in by you.
- **Tooling and ecosystem lag.** Some wheels, profilers and test plugins do not
  yet support `3.14t`.

## How to implement

1. Install a free-threaded interpreter. With uv, use the `3.14t` variant
   (for example `uv python install 3.14t`), and create the workload's venv from it.
   Do not change the project's `requires-python` baseline to do this.
2. Confirm at runtime which build and GIL state you have:

   ```python
   import sys
   import sysconfig


   def is_free_threaded_build() -> bool:
       return bool(sysconfig.get_config_var("Py_GIL_DISABLED"))


   def gil_is_enabled() -> bool:
       # sys._is_gil_enabled() is available from Python 3.13 onward.
       return sys._is_gil_enabled()
   ```

   Use these only for diagnostics and startup logging. Do not branch business
   logic on them; the same code must be correct on both builds.
3. Control the GIL for a run:
   - `PYTHON_GIL=0` in the environment, or `-X gil=0` on the command line, asks a
     free-threaded build to keep the GIL disabled.
   - `PYTHON_GIL=1` / `-X gil=1` re-enables it, which is useful for bisecting a
     problem. Verify these names against the CPython 3.14 "free-threaded Python"
     documentation before copying them into project config.
4. Configuration goes through `Settings`, not `os.getenv()` scattered across
   modules (see [`config.md`](config.md)).
5. Blocking work goes through `run_in_thread()`, which uses the module-level
   `BLOCKING_THREADPOOL` (`max_workers=10` in the reference in
   [`async-patterns.md`](async-patterns.md)), not an ad-hoc `ThreadPoolExecutor`
   (see the guard below). That pool size is hardcoded and does not read `Settings`.
   Under free-threading it caps the real parallelism, so tune it deliberately
   and treat making it configurable as a separate change.

## Dependency compatibility check

Run this before enabling a workload on `3.14t`. It is a documented manual
procedure; the repository does not ship a checker for it.

1. **List the direct and transitive dependencies** from the lock file.
2. **Look for `cp314t` wheels** on PyPI for every compiled dependency. The free-
   threaded ABI tag ends in `t` (for example `cp314-cp314t-manylinux_...whl`).
   A pure-Python package (`py3-none-any`) is fine on any build.
3. **Resolve with the free-threaded ABI**, not the default one:
   - `uv pip compile` (or `uv lock`) against a `3.14t` interpreter, and confirm
     every compiled package resolves to a `cp314t` wheel or an sdist that builds.
   - Or `pip download --python-version 3.14 --abi cp314t --only-binary=:all: -d /tmp/wheels -r requirements.txt`,
     then check that each compiled dependency downloaded.
4. **Confirm `requires-python` still admits 3.14t.** A marker such as
   `requires-python = ">=3.12,<3.15"` admits `3.14t`; an upper bound below 3.14
   or a dependency pinned to `<3.14` blocks it. Check the project's and each
   dependency's metadata, not only the top-level file.
5. **Run the workload's tests on the free-threaded build** and record whether any
   extension re-enabled the GIL (`sys._is_gil_enabled()` returns `True` after
   import of the extension).
6. **Keep the GIL build as the fallback.** A failed check means the workload stays
   on the default build; it is not a reason to change the baseline.

## Guard rules that matter more under free-threading

These rules already exist. Do not change them in this reference; they are listed
so the reader knows why they bite harder once the GIL is gone.

- **Raw thread pools are banned.** The `python-thread-subprocess-guard` hook
  (`src/claude_all/hooks/python-thread-subprocess-guard.py`) blocks raw
  `ThreadPoolExecutor` and `to_thread` use. Under free-threading, an unbounded
  thread pool runs shared code truly in parallel, so pool size and ownership must
  be controlled in one place.
- **Module-level mutable state.** The `process_globals` and `unlocked_singleton`
  checkers flag process-wide mutable singletons. Under the GIL a naive
  check-then-set on a shared dict was usually harmless in practice; under
  free-threading it is a real race. Any singleton shared across threads needs an
  explicit lock or must be immutable.
- **No global mutable state.** The rule in [`SKILL.md`](../SKILL.md) (Quick rules:
  "Global mutable state → pass context objects") is the root cause fix: pass
  context objects instead of sharing module state, and the race surface shrinks
  to the objects you deliberately share.

Together these mean that free-threading multiplies the cost of a missed rule.
The gates stay as they are; they just have to hold on every build that runs the code.

## Lambda

The repository does **not** confirm that AWS Lambda Python runtimes run
free-threaded (`3.14t`) builds. Until the Lambda runtime documentation has been
checked for that specific runtime, treat free-threading as **container or ECS
only**. Do not assume a Lambda handler can select a `t` build. The
`lambda_handler` / `uvloop.run(main(event))` pattern in [`SKILL.md`](../SKILL.md)
is unchanged either way.

## Naming in examples

Use placeholder names only (`myapp`, `my-service`, `myorg/myhook`) in any example
or config snippet added to this reference.
