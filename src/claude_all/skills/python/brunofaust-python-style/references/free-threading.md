# Free-threaded Python 3.14 — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth. This page is about the **free-threaded build** — the 3.14 interpreter compiled without the GIL. For subinterpreter parallelism via `concurrent.futures.InterpreterPoolExecutor` / PEP 734, see [`references/async-patterns.md`](async-patterns.md) — that is a *different* feature and is documented there, not here.

## What "free-threaded" means

Standard Python 3.14 ships with the **GIL** (Global Interpreter Lock): only one thread executes Python bytecode at a time, so threads give you *concurrency* (interleaving) for I/O-bound work but **not** *parallelism* for CPU-bound work. The **free-threaded build** is the same interpreter compiled without the GIL (`--disable-gil`), so genuine multi-core parallelism via threads works without a separate `ProcessPoolExecutor`.

Supporting "no GIL" is a real, ongoing maintenance burden on the CPython runtime, so the free-threaded interpreter is a **separate source distribution and separate install**, not a runtime toggle. It is not the default — you opt in explicitly, and the cost is paid in C-extension compatibility.

### How to tell which build you are running

```python
import sys

# The one supported check — True on the free-threaded build.
free_threaded: bool = sys._is_free_threaded()

# Opposite question — whether the build still runs under the GIL.
gil_enabled: bool = sys._is_gil_enabled()
```

The canonical, supported check is **`sys._is_free_threaded()`** (returns `True` on the free-threaded build). `sys._is_gil_enabled()` exists for the *opposite* question. Do not infer the build from `sys.version` — platform strings like `3.14.1 (+GIL)` vs `3.14.1` are not a stable contract across distributions. Gate on the function:

```python
import sys

IS_FREE_THREADED: bool = sys._is_free_threaded()
```

### How to obtain / enable it

The free-threaded build is a distinct interpreter. It is not a flag you flip on a normal install.

```bash
# uv — enable free-threading on the toolchain
uv python install 3.14 --enable-free-threading

# python.org — separate free-threaded installer / build (non-Windows)
./configure --with-freethreaded-python  # then make -j && make altinstall

# uv — pin a project to the free-threaded interpreter in pyproject.toml
# (uv >= 0.6.8; requires-python >= 3.14 and the freethreaded toolchain)
```

```toml
[project]
requires-python = ">=3.14"

[tool.uv]
python-preference = "only"
# and install/run with a freethreaded-marked interpreter, e.g.
# uv run --python 'cpython-3.14.1+freethreaded-...' your_command
```

The GIL is configured **once, when the interpreter binary is built** — a normal `cpython-3.14` binary cannot become free-threaded, and a free-threaded binary cannot turn the GIL back on. Treat it as an environment/CI decision, not an application flag. In a mixed fleet, gate startup on `sys._is_free_threaded()` and pick the correct pool strategy per runtime.

## When to use it — and when not to

Reach for free-threading only when you have **CPU-bound pure-Python work** that would otherwise need `ProcessPoolExecutor` or `InterpreterPoolExecutor`. The comprehensive answer lives in the decision table below.

| Situation | GIL build | Free-threaded build |
| --- | --- | --- |
| I/O-bound async (the default here) | ✅ — threads/async interleave fine | ⚠️ no benefit; pay the C-extension compatibility cost for nothing |
| CPU-bound pure Python (parsing, transforms, crypto of your own code) | ❌ — GIL serialises threads | ✅ — the one real win; real multi-core parallelism |
| CPU-bound C extension (Polars, NumPy) | ✅ — already releases the GIL | ⚠️ extension must be free-threaded-compatible; benefit often already captured via the extension releasing the GIL |
| Blocking I/O offload (`run_in_thread`) | ✅ | ✅ — unchanged |
| Shared mutable state via threads | ❌ — GIL is a crude safety net | 🔴 — **no GIL means real races**; you now own thread-safety discipline |

This skill is **async-first**, and uvloop + `asyncio` deliver concurrency without threads — so for the *overwhelming* majority of code here, free-threading buys nothing. The honest default is: **stay on the GIL build unless you can point at a hot CPU-bound pure-Python section you have measured.** That is the YAGNI test applied to the interpreter itself (see [`references/yagni.md`](yagni.md)).

## Pros and cons

### Pros

1. **True multi-core parallelism for pure-Python CPU work** — threads actually run in parallel; a 4-core box can speed up a hot pure-Python loop ~4× without `ProcessPoolExecutor` (no IPC, no pickling, no fork).
2. **Shared-memory concurrency without copy** — threads share objects with zero-copy, unlike processes which isolate the heap.
3. **Lower overhead than `ProcessPoolExecutor`** — no serialisation at the boundary, no process startup/fork latency.

### Cons

1. **C-extension compatibility is the hard gate** — any extension compiled for the GIL build (or that links against a whole-application library that assumes the GIL) is a **crash or corruption risk**, not a slow-down. This is the #1 reason teams don't adopt it.
2. **You inherit full thread-safety discipline.** With the GIL gone, `list`/`dict` mutation from two threads is a *true* data race. The GIL was a (weak) safety net that hid many bugs; that net is removed.
3. **Some stdlib/`ctypes`/C-FFI paths behave differently** (or remain internally GIL-guarded, or refuse to work) — read each dependency's free-threading statement.
4. **Operational overhead** — a separate interpreter to build, toolchain to pin, CI matrix to extend, and per-dependency compatibility tracking.
5. **Performance is not a guaranteed win** — small tasks and lock-free-but-allocating hotspots can get *slower* due to per-object reference-count manager (PERC) work; single-threaded code is typically a small constant slower than the GIL build.

## How to implement it

### 1. Detect the runtime and default conservatively

```python
import sys

# Constant per build — evaluate once at import, treat as read-only.
IS_FREE_THREADED: bool = sys._is_free_threaded()
```

### 2. Use the right concurrency primitive for the work

The decision table (extends the one in `async-patterns.md`):

| Work | Use |
| --- | --- |
| I/O-bound, async | `asyncio` / `TaskGroup` / `uvloop` — threads not needed |
| Blocking I/O offload | `run_in_thread()` (`async-patterns.md`) |
| CPU-bound pure Python | **GIL build:** `InterpreterPoolExecutor` / `ProcessPoolExecutor` — **free-threaded build:** threads (or keep `InterpreterPoolExecutor`) |
| Subinterpreter parallelism | `concurrent.futures.InterpreterPoolExecutor` — works on both, see `async-patterns.md` |
| C extension (releases GIL) | `run_in_thread()` — extension already parallelises |

```python
from concurrent.futures import ThreadPoolExecutor
import sys


def _cpu_heavy_pure(items: list[int]) -> list[int]:
    """CPU-bound pure-Python work — genuinely parallel only when free-threaded."""
    return [int(round(x ** 1.5)) + 1 for x in items]  # illustrative


def run_parallel(items: list[int]) -> list[int]:
    """Run pure-Python CPU work across cores where the build allows it."""
    if sys._is_free_threaded():
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(_cpu_heavy_pure, items))
    # GIL build: threads would serialise — fall back to a subinterpreter/process.
    from concurrent.futures import InterpreterPoolExecutor

    with InterpreterPoolExecutor(max_workers=8) as pool:
        return list(pool.map(_cpu_heavy_pure, items))
```

### 3. Own thread-safety explicitly (no GIL safety net)

With free-threading, shared state mutated from more than one thread is a real race. The skill's standing rules already aim here — honour them strictly:

- **No global mutable state; pass context objects** (see [`references/config.md`](config.md) and [`references/tenant-isolation.md`](tenant-isolation.md)).
- Prefer **immutable** data (`Mapping`/`Sequence`, frozen Pydantic models) across thread boundaries.
- Guard the few genuinely-shared mutable structures with `threading.Lock` / `RLock` — never rely on an implicit interlock.
- `dis`-level bytecode that "happened to be atomic" under the GIL is **not** atomic without it — treat composite read-modify-write as non-atomic.

## How to check dependency compatibility (C extensions & GIL)

C extensions are the make-or-break for free-threading. A crash is silent and corrupting — never assume, always verify. The recipe is manual + automated.

### 1. Ask the package / upstream

- Read the package's **free-threading support statement** (changelog, README, packaging metadata). Most scientific C extensions (NumPy, Polars) declare support in the `3.14t` tag; pure-Python wheels are unaffected.
- Check **PyPI wheel tags**: a free-threaded compatible wheel carries the **`t`** suffix in its platform tag — e.g. `numpy‑2.3.0‑cp314‑cp314t‑manylinux_2_17_x86_64.whl`. `cp314t` = the free-threaded (`t` for "threads") ABI. A plain `cp314` wheel was built against the GIL build.

### 2. Inspect whether an extension imports/uses the GIL

Source-level signals that an extension assumes the GIL:

```python
import importlib.metadata

# Report which installed distributions ship a binary extension — those are the
# ones whose free-threading compatibility you actually have to check.
for dist in importlib.metadata.distributions():
    files = dist.files or ()
    has_ext = any(str(f).endswith((".so", ".pyd", ".dylib")) for f in files)
    if has_ext:
        print(f"{dist.metadata.get('Name', 'unknown')!r} ships a native extension")
```

That dist listing only finds *presence*. The decisive checks on the **running** interpreter are runtime probes:

```python
import sys

# Depends on the build, never on the platform string.
if not sys._is_free_threaded():
    print("GIL build — native extension GIL-dependence is largely moot.")
    raise SystemExit(0)

# On the free-threaded build, import every native dependency early. A clean
# import under `-X verify` free-threading is the practical import-safety check;
# a failing or freezing import is an immediate red flag.
#   python -X verify -m myapp
```

### 3. Use `-X verify` / free-threaded runtime probes

CPython provides a verification-oriented execution mode; run your test suite under it on the free-threaded interpreter:

```bash
# Run the suite on the free-threaded interpreter with verification enabled.
uv run --python 'cpython-3.14.1+freethreaded-...' python -X verify -m pytest -n auto
```

`-X verify` tightens checks that catch GIL-unsafe C extensions and object-lifetime bugs. A green suite under `-X verify` free-threaded is strong evidence a project's extension stack is compatible **for the code paths the tests exercise** — it can never prove all paths.

### 4. Automate the scan (metadata + tags)

```bash
# List installed distributions that ship a native extension, so you know exactly
# which ones need a `cp314t` wheel before you can go free-threaded.
python - <<'EOF'
import importlib.metadata

for dist in importlib.metadata.distributions():
    files = list(dist.files or ())
    has_ext = any(str(f).endswith((".so", ".pyd", ".dylib")) for f in files)
    if has_ext:
        print(dist.metadata.get("Name", "unknown"), dist.version, "ships native code")
EOF
```

The reliable place to *enforce* this is **the resolver**: `uv` resolves the free-threaded interpreter's `t`-tagged wheels and will *fail resolution* when a required native dependency has no free-threaded wheel. That is the column you actually rely on — a manual fold-check is the fallback for eyeballing, not the gate.

### 5. Guard against the silent-fail class in `pyproject.toml`

If a project must run on both builds, express the constraint so the resolver enforces it:

```toml
[project]
requires-python = ">=3.14"

# No blanket "any 3.14" claim: name the free-threaded-only pieces if any.
# e.g. a pure-Python package (no native ext) is inherently compatible, so
# nothing more is needed in pyproject for THIS package.
```

### InterpreterPoolExecutor on the free-threaded build

`concurrent.futures.InterpreterPoolExecutor` (PEP 734) is available on **both** the GIL and free-threaded builds and is the right tool for CPU-bound work regardless. On the GIL build it is the parallelism primitive beside threads; on the free-threaded build threads also parallelise, so prefer the simpler `ThreadPoolExecutor` for pure-Python CPU work. Details and limitations live in `references/async-patterns.md` — do not duplicate them here.

## Bottom line

- **Default: stay on the GIL build.** Free-threading is an opt-in for a measured, hot, CPU-bound pure-Python section — the YAGNI test applied to the runtime.
- **Detect with `sys._is_free_threaded()`**, never by parsing `sys.version`.
- **The gate is C-extension compatibility**, verified by `cp314t` wheel tags, upstream statements, and a `-X verify` free-threaded test-suite run — never assumed.
- **No GIL means real races** — the implicit thread-safety net is gone; shared state must be protected explicitly.
- For subinterpreters use `InterpreterPoolExecutor` (`async-patterns.md`); do not conflate the two features.
