# Free-threaded Python 3.14 (PEP 703) — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps
> a condensed summary; this file holds the full depth.

This file covers **PEP 703 free-threading** — the interpreter *build* with the
Global Interpreter Lock removed (`--disable-gil`, the `python3.14t` binary, abiflag
`t`). It is **not** PEP 734 subinterpreters (`concurrent.futures.InterpreterPoolExecutor`),
which is a different 3.14 feature with a different concurrency model — that one is
covered in [`async-patterns.md`](async-patterns.md). Do not conflate them:

| | Free-threading (PEP 703, this file) | Subinterpreters (PEP 734) |
| --- | --- | --- |
| Mechanism | One interpreter, no GIL — plain threads run Python bytecode truly in parallel | Multiple interpreters in one process, each with its own GIL |
| API surface | Normal `threading` code — no new API | `InterpreterPoolExecutor` |
| Data sharing | Shared memory (this is the point — and the hazard) | Isolated; picklable/`memoryview`-style payloads only |
| Dependency requirement | Every C extension must ship a free-threaded build (`cp314t`) | Extensions must be multi-interpreter-safe |

## When to use — and when not to

The skill's baseline is **async-first**: `uvloop.run()` entry points, all custom
functions `async def`, blocking work offloaded through `run_in_thread()`. That
architecture does not change. Free-threading is an **opt-in runtime for a specific
workload shape**, not a replacement for asyncio and not a reason to rewrite.

**Reach for the free-threaded build when ALL of these hold:**

- The hot path is **CPU-bound pure-Python** — parsing, transformation, scoring,
  serialization loops that never yield the GIL on a default build.
- The parallelism you want is **thread-local** — many threads over shared, read-mostly
  state (a loaded model, a config snapshot, an in-memory index). No per-task process
  creation, no pickling cost.
- You have measured (or can cheaply measure) that the workload is CPU-bound, not
  I/O-bound — free-threading does **nothing** for I/O-bound code.

**Do NOT reach for it when:**

- The workload is I/O-bound — asyncio + `uvloop` already wins there; threads add
  nothing. (The default case for this skill's services: AWS calls, DB queries, HTTP.)
- The CPU-bound work sits in C extensions that already release the GIL (Polars,
  numpy, orjson) — those parallelize across threads fine on the *default* build;
  keep `run_in_thread()`.
- You only need isolated parallel tasks with no shared state — prefer
  `InterpreterPoolExecutor` (PEP 734, see `async-patterns.md`) and skip the
  ecosystem-compatibility tax below.
- A dependency you cannot replace lacks a free-threaded build — see the
  compatibility checklist; one unpinned native dep silently re-enables the GIL
  and you get the cost of the build with none of the parallelism.

## Pros and cons

| Pros | Cons |
| --- | --- |
| True parallelism for pure-Python threads without multiprocessing overhead (no pickling, no IPC, shared memory) | Small single-threaded overhead vs a default build (biased reference counting, per-object locks, mimalloc) — measure before committing |
| Threads become a cheap, honest primitive — no more "threads are useless in CPython" contortions | Memory usage grows (per-object lock words, deferred refcount metadata) |
| `run_in_thread()` offloads of *pure-Python* functions now actually scale across cores | Every C/C++/Rust extension you import must ship a free-threaded wheel; one non-`cp314t` extension re-enables the GIL at import time |
| Shared in-memory state (caches, registries) needs no serialization boundary | Your own code (and your deps') latent thread-safety bugs stop being hidden by the GIL — racy check-then-act sequences now actually race |
| | Ecosystem coverage is still maturing; some native deps pin versions to add `t` wheels |
| | Tooling lags: some profilers/debuggers/observability agents assume the GIL |

## How to implement

### 1. Run the free-threaded interpreter

Free-threading is a **build variant**, not a flag on a stock interpreter. Install
the `t` build and create the project venv from it:

```bash
# Install the free-threaded 3.14 build (the `t` suffix selects it)
uv python install 3.14t

# Bootstrap the project venv against it
uv venv --python 3.14t
```

At runtime the binary is named `python3.14t`; `sys.abiflags` contains `"t"`.
(For the language baseline, `requires-python`, and the prek `language_version`
pin, nothing changes — the `t` build speaks the same 3.14 syntax. See
[`pyproject-toml.md`](pyproject-toml.md).)

### 2. Verify the GIL is actually off

Never assume — assert it:

```python
import sys
import sysconfig


# Free-threaded build indicator (1 on the `t` build).
assert sysconfig.get_config_var("Py_GIL_DISABLED") == 1

# Runtime check: False means the GIL is currently disabled.
# NOTE: it can flip to True at import time when a C extension that was not
# built for free-threading gets imported — check AFTER all imports.
assert sys._is_gil_enabled() is False
```

The `-X gil` flag and `PYTHON_GIL` env var force the runtime behavior on a `t`
build — `PYTHON_GIL=1 python script.py` gets you the old behavior back for
A/B benchmarking, which is the honest way to measure whether free-threading
helps your workload:

```bash
PYTHON_GIL=1 python -m myapp.benchmark   # baseline: GIL on
PYTHON_GIL=0 python -m myapp.benchmark   # free-threaded
```

### 3. Write thread-correct code — the GIL was never your lock

The GIL serialized *bytecode*, not *logic*. Code that was accidentally safe under
the GIL can now race. Audit these patterns:

```python
# BROKEN now: check-then-act on shared state — two threads both pass the check.
if key not in shared_cache:
    shared_cache[key] = expensive_build()

# CORRECT: one lock per invariant, held across the whole decision.
with cache_lock:
    if key not in shared_cache:
        shared_cache[key] = expensive_build()
```

Rules:

- **Compound operations need a lock.** `list.append(x)` is still atomic; `d[k] += 1`
  (load-add-store) is not, and neither is any check-then-act sequence.
- **Module-level lazy initialization must be locked** — the classic
  `if _instance is None: _instance = ...` singleton is a textbook GIL-hidden race.
- **Iterating a structure another thread mutates now crashes/flakes** instead of
  usually working — snapshot (`list(d)`) or lock.
- **Use `concurrent.futures.ThreadPoolExecutor` / `asyncio` TaskGroups for
  fan-out** — same structured-concurrency rules as the rest of this skill; raw
  `threading.Thread` still needs the ownership story (see `async-patterns.md`).
- **Do not sprinkle locks speculatively** (YAGNI) — audit the *shared mutable*
  state, lock that, and leave thread-local and immutable data lock-free.

### 4. Keep the async-first architecture

Free-threading layers onto the existing pattern, unchanged:

- Entry points stay `uvloop.run(main(...))` — asyncio for I/O.
- `run_in_thread()` stays the single offload seam; its pool is where a
  free-threaded build converts CPU-bound pure-Python offloads into real
  parallelism. Size the pool to cores, not "a bit more for blocking I/O".
- Polars / orjson / native-extension calls stay on `run_in_thread()` either way —
  they released the GIL already.

## Checking dependency compatibility

Free-threading is all-or-nothing **per process**: every C extension in the import
graph must support it, or CPython re-enables the GIL at the first incompatible
import and silently downgrades you to single-threaded-ish behavior with the
build's overhead still attached. Check in this order:

1. **Wheel tags.** A compatible extension publishes wheels tagged `cp314t`
   (or an `abi3` wheel explicitly built for free-threading). Check each dependency
   on PyPI for a `*-cp314t-*.whl` file. No `cp314t` wheel → not compatible.
2. **The runtime canary.** Import the package under the `t` build and assert the
   GIL stayed off. An extension not built for free-threading makes CPython emit
   a `RuntimeWarning` ("...has been enabled") and re-enable the GIL — catch either:

   ```python
   import sys
   import warnings

   with warnings.catch_warnings(record=True) as caught:
       warnings.simplefilter("always")
       import some_native_dep  # noqa: F401

       assert sys._is_gil_enabled() is False, (
           f"GIL re-enabled by an incompatible extension: {caught}"
       )
   ```

   Run this from a script that imports every direct dependency — it belongs in CI
   as a compatibility gate.
3. **Declared support.** Look for the PyPI trove classifier
   `Programming Language :: Python :: Free Threading :: *` on each dependency —
   it signals the maintainers test against the `t` build, including releases.
4. **Thread-safety testing.** Pure-Python deps with no `t` wheels are not the
   blocker (they import fine) — the blocker for *them* is thread-unsafe code.
   Run the suite with [`pytest-run-parallel`](https://pypi.org/project/pytest-run-parallel/)
   (`pytest --parallel-threads=10`) to shake out races in your own code and in
   pure-Python deps.
5. **Matrix CI.** Add a `python: 3.14t` job (or run the full suite under
   `PYTHON_GIL=0`) so a new incompatible transitive dep fails CI instead of
   silently downgrading production.

If a blocking native dep ships no `cp314t` wheel: treat free-threading as
**blocked for that service** — stay on the default build and use
`InterpreterPoolExecutor` for CPU parallelism instead. Do not fork, patch, or
pin-forever a native library to chase this.

## Decision summary

- Default for this skill's services (I/O-bound, dockerized, async-first): **stay
  on the default build**.
- CPU-bound pure-Python service with measured GIL contention: **evaluate the `t`
  build** — run the compatibility checklist, A/B with `PYTHON_GIL=0/1`, adopt only
  if the numbers say so.
- Isolated parallel tasks: `InterpreterPoolExecutor` (see `async-patterns.md`).
- Never adopt free-threading by accident — the interpreter choice is a deliberate,
  measured, per-project decision recorded in the project README.
