# Free-threaded Python 3.14t

The free-threaded build (`3.14t`, PEP 779) runs without the global interpreter lock (GIL). Threads can run Python bytecode in parallel. The baseline in [`SKILL.md`](../SKILL.md) stays **Python 3.12+**; this reference only decides whether a project may opt into the `3.14t` build, and how to prove that its dependencies work on it.

## Stance

- **Not the default.** The standard `3.14` build stays the project default. Do not change `requires-python`, the prek `language_version`, or CI interpreters to `3.14t` because this reference exists.
- **Adopt only for a named workload.** Opt in when a specific CPU-bound pure-Python workload runs on shared in-process state, and measurement shows that threads are the bottleneck.
- **Otherwise keep the current guidance.** Blocking C-extension and file or network I/O calls still go through `run_in_thread()`. Pure-Python CPU work that does not need shared mutable state still goes through `InterpreterPoolExecutor` (see [`async-patterns.md`](async-patterns.md)).

## When to use it

Use the `3.14t` build for a project or a service only when all of these hold:

1. The hot path is **pure-Python CPU work** (parsing, scoring, transformation loops) that cannot be moved into a C or Rust extension that already releases the GIL.
2. The work must **share mutable in-process state** between threads, which `InterpreterPoolExecutor` cannot do (interpreters are isolated and only exchange picklable or shareable values).
3. A benchmark on the standard build shows threads are the limit, and the expected gain has been measured on the free-threaded build with the project's real workload.
4. Every runtime dependency on the hot path has been checked for free-threaded support (see the compatibility procedure below).

Do not use it for:

- I/O-bound code. `await` on the async clients already overlaps I/O on one thread.
- Work that Polars, orjson, or other extensions already do in native code.
- Code paths whose only parallelism need is "run several jobs" — separate processes or Lambda invocations do that without thread-safety work.

## Pros and cons

| Aspect | Free-threaded `3.14t` | Standard `3.14` |
| --- | --- | --- |
| CPU-bound pure Python on threads | True parallelism across cores | Serialised by the GIL |
| Single-thread speed | Typically slower for pure-Python code (extra locking and specialisation costs); measure it | Baseline |
| Memory use | Typically higher | Baseline |
| Extension modules | Must declare free-threading support; otherwise the GIL is re-enabled at import | Unaffected |
| Shared-state bugs | Races that the GIL used to hide become visible | Races are rarer but still possible |
| Tooling and CI | Every wheel, lockfile, and test run needs a `3.14t` interpreter | Current setup |
| Subinterpreters / `InterpreterPoolExecutor` | Still available; they remain the isolation option | Available |

Net effect: free-threading helps only when the parallel CPU work is large enough to outweigh the single-thread cost and the dependency risk.

## Interaction with the existing guidance

- **`run_in_thread()`** — keeps its role for blocking C extensions and blocking I/O. On `3.14t` these calls can overlap in real threads, but the single owned pool and its size from settings still apply. Do not replace the pool with unbounded threads.
- **`InterpreterPoolExecutor`** — still the choice when work is pure Python and needs no shared mutable state. Free-threading does not replace it; it is an alternative for the shared-state case that subinterpreters cannot serve.
- **Thread-safety checklist** — the "Thread-safe" item in [`SKILL.md`](../SKILL.md) applies directly. On `3.14t` every module-level mutable object, cache, and lazily built singleton that is reachable from more than one thread needs an explicit lock, an immutable design, or a per-thread owner. Do not rely on the GIL making a `dict` update or a check-then-set atomic.

## How to implement it

### 1. Install a free-threaded interpreter

```bash
uv python install 3.14t
uv venv --python 3.14t .venv-ft
```

Use a separate virtual environment so the standard environment stays untouched. Inspect the build with a one-line check:

```bash
.venv-ft/bin/python -c "import sysconfig, sys; print(sysconfig.get_config_var('Py_GIL_DISABLED'), sys._is_gil_enabled())"
```

`Py_GIL_DISABLED` is `1` on a free-threaded build. `sys._is_gil_enabled()` reports whether the GIL is active in the running process.

### 2. Control the GIL at runtime

- `PYTHON_GIL=0` — request that the GIL stay disabled for the process. Use it when measuring or running the service.
- `PYTHON_GIL=1` — force the GIL on, useful to isolate whether a problem is free-threading specific.
- Verify at startup in a test or a diagnostic, not by assumption:

```python
import sys


def gil_enabled() -> bool:
    """Report whether this process runs with the GIL active."""
    return sys._is_gil_enabled()  # noqa: SLF001 — diagnostic only, 3.13+
```

Keep such a diagnostic in one owner module. Do not scatter `sys._is_gil_enabled()` calls through business logic, and do not branch behaviour on it: the code must be correct either way.

### 3. Never rely on the GIL for correctness

Shared-state safety must come from design, not from the interpreter:

- Prefer immutable inputs (`Mapping`, `Sequence`, frozen Pydantic models) and pass results back rather than mutating shared structures.
- Guard any shared mutable object with a `threading.Lock` (or equivalent) held around the whole read-modify-write.
- Cache objects reachable from several threads need a lock on the fill path. The caching rules in [`caching.md`](caching.md) still apply.
- Run the concurrency tests under the free-threaded interpreter with several threads, not only under the standard build.

## How to check dependency compatibility (manual procedure)

Free-threaded status is per package and per version, and it changes over time. Verify each package yourself; do not rely on a list copied into a document. Use the following steps for each runtime dependency on the hot path, and record the result in the project's own notes.

1. **Look for a free-threaded wheel.** On the package's PyPI release page, check the file list for a wheel tagged `cp314t` (for example `...-cp314-cp314t-...whl`). A pure-Python wheel (`py3-none-any`) works on any build. A source-only release means you must build it, so check the build logs for the free-threading flag.
2. **Resolve against a `3.14t` interpreter.** Run `uv lock` or `uv sync` with the free-threaded interpreter selected (for example `uv sync --python 3.14t`) and read what it resolves. A missing `cp314t` wheel with no sdist fails here.
3. **Import every hot-path dependency under `3.14t`, without `PYTHON_GIL` set.** Run a short script that imports each module in turn and prints the GIL state after each one:

   ```bash
   .venv-ft/bin/python -W error::RuntimeWarning -c "
   import importlib, sys
   for name in ['polars', 'orjson', 'cachebox', 'pydantic', 'structlog', 'uvloop']:
       importlib.import_module(name)
       print(name, 'GIL enabled:', sys._is_gil_enabled())
   "
   ```

   Do not set `PYTHON_GIL=0` for this step: it keeps the GIL off, which hides the re-enable this check relies on. If an extension has not declared free-threading support, the interpreter emits a `RuntimeWarning` and re-enables the GIL at import; `-W error::RuntimeWarning` turns that into a failure, and the last module printed before the traceback is the one involved. Treat it as a failed check: the dependency is not safe to run in parallel on that build. A module that prints `GIL enabled: True` after its import is also a failure for the parallel workload.
4. **Run the test suite under `3.14t`.** Run the full suite with the free-threaded environment, and run the concurrency-sensitive tests repeatedly with several workers. Real-infra tests (see [`testing.md`](testing.md)) run the same way.
5. **Benchmark the workload.** Compare the standard build with the free-threaded build (`PYTHON_GIL=0`) on the real hot path. Keep the change only if the measured gain justifies the single-thread cost and the extra dependency risk.
6. **Re-check on each dependency upgrade.** A new release can drop or add free-threaded support. Repeat steps 1–4 when a hot-path dependency is bumped.

Record the outcome per package in the project: the version checked, the interpreter used, whether a `cp314t` wheel or a source build was used, and whether the import emitted a `RuntimeWarning`.

## Checklist

- [ ] Workload is named, CPU-bound, pure Python, and needs shared in-process state
- [ ] Benchmark on the real workload shows threads are the limit
- [ ] Every hot-path dependency verified under `3.14t` (wheel or build, no GIL re-enable warning)
- [ ] Shared mutable state guarded by design or lock; no reliance on the GIL
- [ ] Concurrency tests green under `3.14t` across repeated runs
- [ ] Project default interpreter, `requires-python`, and prek `language_version` left unchanged unless a separate decision says otherwise
