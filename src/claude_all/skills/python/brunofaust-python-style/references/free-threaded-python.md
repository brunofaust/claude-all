# Free-threaded Python — workload-specific guide

> Reference page for the `brunofaust-python-style` skill. Free-threaded CPython is
> an optional deployment/runtime choice; the skill's Python 3.12+ language baseline
> and async-first design remain unchanged.

## When to use it

Consider Python 3.14's free-threaded build (`python3.14t`) when measured CPU-bound
work can run concurrently across Python threads and the workload is limited by the
GIL. Benchmark representative application workloads before adopting it. It can also
be useful when an application depends on real parallel execution across threads.

Do not select it by default just because the application is async. Async concurrency
is effective for I/O-bound workloads and does not require disabling the GIL. It does
not make a single-threaded CPU workload faster, and processes may remain a better
choice for isolation or workload-specific performance.

## Benefits and costs

**Potential benefits**

- Python threads can execute Python code in parallel across CPU cores.
- Thread-based concurrency may avoid some process startup, serialization, and
  inter-process communication overhead.

**Costs and risks**

- Python 3.14's free-threaded build is a separate build/runtime; it is not the
  default interpreter and does not change the project's 3.12+ syntax baseline.
- Some workloads are slower due to synchronization and runtime overhead; benchmark
  rather than assuming a speedup.
- C extensions and their transitive dependencies may not support free-threading.
  An unsupported extension can cause the GIL to be enabled at runtime.
- Removing the GIL does not make shared mutable state safe. Add appropriate
  synchronization and test concurrent access; avoid relying on incidental
  interpreter serialization.
- Tooling, wheels, deployment images, and platform support may differ from the
  regular interpreter.

## Enable and verify the runtime

Install and invoke the free-threaded interpreter explicitly. For example, on
Windows the Python launcher can install and run it as follows:

```bash
py install 3.14t
py -3.14t --version
```

On other platforms, use the platform's supported Python 3.14 free-threaded
installation and verify the executable selected by the environment manager. Keep
separate environments for regular and free-threaded interpreters; do not assume a
virtual environment created by one build is interchangeable with the other.

Check the active interpreter at startup or in a diagnostic script:

```python
import sys

if not hasattr(sys, "_is_gil_enabled"):
    raise RuntimeError("This CPython build cannot report its GIL state")
if sys._is_gil_enabled():
    raise RuntimeError("Expected free-threaded CPython, but the GIL is enabled")
```

`sys._is_gil_enabled()` is a CPython implementation detail. A free-threaded build
can start with the GIL disabled but enable it when an extension does not declare
free-threading support. Check the runtime state after importing the application's
native dependencies, not only in a bare interpreter. Avoid setting `PYTHON_GIL=0`
or `-X gil=0` as a substitute for compatibility: forcing the GIL off can expose
unsafe extension behavior.

## Check dependency compatibility

Use both package metadata and execution checks; neither proves compatibility alone.

1. **Inventory direct and transitive dependencies.** Identify packages with C/C++,
   Rust, Cython, or other native extensions. Pure-Python packages avoid many binary
   compatibility issues but still need concurrency tests.
2. **Check published support evidence.** Review the package's documentation, release
   notes, issue tracker, and wheel availability for CPython 3.14 free-threaded
   support. In wheel tags or distribution metadata, look for the free-threaded
   `t` ABI where relevant. A claim of general Python 3.14 support or an installable
   wheel alone does not establish that free-threaded execution is supported.
3. **Install in a clean free-threaded environment.** Use a current installer
   (pip 24.1 or newer for free-threaded extension wheels) and run the project's
   normal dependency lock/install workflow. Resolve missing wheels or source-build
   failures explicitly; do not silently fall back to a regular interpreter.
4. **Run the GIL-state check after imports.** Import the full application dependency
   set under the candidate runtime, then assert `not sys._is_gil_enabled()`.
   Investigate warnings about extensions and GIL enabling; an enabled GIL means
   this run is not exercising free-threaded execution.
5. **Run tests and representative benchmarks in both runtimes.** Include stress
   tests for shared state, callbacks, caches, and native extensions. Compare
   correctness and performance against the regular build before making the runtime
   a production option.

For extension authors, consult CPython's free-threading extension guidance. Native
modules must be built for the free-threaded ABI and explicitly declare whether they
support running without the GIL (for example with the `Py_mod_gil` module slot for
multi-phase initialization). Do not claim support unless native state and C-API
access are safe under concurrent execution.

## Decision rule

Adopt the free-threaded build only when a benchmark demonstrates a relevant benefit,
all important dependencies work without re-enabling the GIL, and the team can test
and deploy both the interpreter and its native package set. Otherwise keep the
regular runtime; async-first application design remains applicable either way.
