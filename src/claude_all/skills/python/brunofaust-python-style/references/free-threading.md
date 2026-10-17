# Free-threaded Python — full reference

> Reference page for the `brunofaust-python-style` skill. Free-threading supplements the Python 3.12+ baseline; it does not replace it.

## Recommendation

Treat free-threaded CPython 3.14 as an **optional deployment target**, not the skill's default. Adopt it only when profiling shows substantial CPU-bound Python work that can run concurrently, the target platforms provide the build, and the complete dependency stack passes compatibility and performance tests. Keep a conventional-GIL build available wherever supported Python versions or deployment platforms require it.

Free-threading removes the interpreter-wide GIL constraint, allowing Python threads to execute Python code in parallel across cores. It does not automatically make code faster or thread-safe. Existing async-first guidance and the owned `run_in_thread()` seam still apply for blocking operations; consult [`async-patterns.md`](async-patterns.md) for those patterns.

## When to consider it

Good candidates include measured, CPU-bound workloads with independent tasks and meaningful work per task: Python-heavy parsing, transformations, or calculations. Benchmark representative production-like workloads, including serialization, memory use, startup, and contention.

Do not choose free-threading merely because a workload uses threads. It is usually not the first choice for:

- **I/O-bound async work:** async concurrency generally addresses waiting efficiently without a free-threaded runtime.
- **Native code that already releases the GIL:** threads may already execute its compute kernels in parallel.
- **Tiny tasks or highly contended shared state:** scheduling and synchronization can outweigh parallelism.
- **Workloads dominated by processes, remote services, or database latency:** the interpreter build does not remove those bottlenecks.

Compare the free-threaded build against the regular-GIL build and the current design. Retain it only if measured end-to-end benefits justify the operational and compatibility costs.

## Benefits and costs

**Potential benefits**

- Python threads can execute Python code in parallel on multiple cores without the GIL serializing execution.
- Thread-based designs can share process memory without the serialization and process-management costs of multiprocessing.
- Existing thread-oriented workloads may gain throughput when their work and dependencies are suitable.

**Trade-offs**

- The free-threaded build can have higher memory use and some single-thread performance overhead; results depend on workload and Python release.
- Dependencies, especially C extensions, may lack compatible builds or may enable the GIL at import time. Compatibility can vary by version and platform.
- Shared mutable state now has real concurrent access. Built-in container safety is not a substitute for application-level invariants or synchronization.
- Deployment, observability, debugging, wheels, and support matrices require additional validation. Some platforms do not offer the required runtime or packages.

## Runtime and deployment requirements

Free-threaded CPython is a separate build, commonly identified by the `t` ABI tag (for example, a `python3.14t` executable). Installing ordinary Python 3.14 does not by itself mean the GIL is disabled. Confirm the exact executable, OS/architecture, container image, hosting environment, and package availability for every deployment target before adopting it.

Build and test against the free-threaded interpreter explicitly. Pin and deploy that runtime consistently in local development, CI, containers, and production. Keep the project's supported-version baseline honest: if Python 3.12 or a platform without a free-threaded build remains supported, code and packaging must continue to work there too. Do not make 3.14t a global requirement solely because one workload benefits.

At runtime, an extension that is not marked as free-threading-compatible can cause the GIL to be enabled. Check the effective runtime state rather than inferring it from the executable name:

```python
import sys

if hasattr(sys, "_is_gil_enabled"):
    print(f"GIL enabled: {sys._is_gil_enabled()}")
```

`sys._is_gil_enabled()` is CPython-specific and underscored; use it for diagnostics and test assertions, not as a portable application API. Verify after importing the actual application dependencies, because imports can change the effective state.

## Implementation checklist

1. **Profile first.** Identify a CPU-bound Python hot path and capture baseline throughput, latency, CPU utilization, memory, and single-thread performance on the conventional build.
2. **Find actual parallelism.** Split work into independent units; avoid shared mutable data where possible. Threads should receive immutable inputs and return results, with a small, explicit synchronization boundary when shared state is unavoidable.
3. **Use bounded concurrency.** Reuse the project's owned thread-pool wrapper (`run_in_thread()` for blocking calls) and configure a bounded pool. Do not create unbounded threads or bypass the existing thread-offload seam. For a CPU-parallel worker pool, make executor choice and lifecycle explicit and test shutdown/cancellation behavior.
4. **Audit invariants and external resources.** Protect compound read/modify/write operations with appropriate locks or ownership. Do not assume a container operation being internally safe makes a multi-step business invariant atomic. Check clients, caches, module globals, callbacks, and extension state for concurrent use.
5. **Preserve portability.** Avoid importing 3.14-only APIs on code paths that must run on 3.12+. Isolate optional runtime-specific behavior and test both supported interpreter configurations.
6. **Benchmark and load-test.** Test realistic concurrency, task sizes, failure/cancellation paths, and contention. Confirm the GIL remains disabled after importing the full dependency set, and measure the end-to-end workload rather than a synthetic microbenchmark alone.

Free-threading is not a replacement for async I/O. Asyncio still schedules tasks on an event loop; use it for I/O concurrency as before. Use threads when synchronous work must be offloaded, and consider the free-threaded build when measured Python CPU work can benefit from parallel threads.

## Checking dependency compatibility

Compatibility must be established for the **exact versions, extras, platform, and architecture** being deployed; a package's general statement that it supports Python 3.14 is not proof that its extension is safe with the GIL disabled.

1. **Inspect the package's official documentation, release notes, issue tracker, and wheel availability** for explicit free-threaded CPython support. Confirm a wheel exists for the desired `cp314t` platform tag or that the supported build-from-source path is documented. A regular `cp314` wheel is not a free-threaded wheel.
2. **Include transitive dependencies.** Inventory native extensions and packages that wrap C, C++, Rust, or other native code; pure-Python packages can still make unsafe assumptions about shared state.
3. **Install into a clean free-threaded environment** using the intended lockfile and production install command. Do not silently fall back to a regular interpreter or an unreviewed source build.
4. **Run the complete test suite and stress tests on that interpreter**, including parallel calls, shared-state boundaries, extension-heavy features, startup/import paths, and shutdown. Run the same compatibility suite on the regular-GIL interpreter if it remains supported.
5. **Check effective GIL state after imports** with `sys._is_gil_enabled()` on CPython. An enabled GIL may indicate an extension activated it; identify and resolve the dependency before claiming free-threaded operation.
6. **Repeat on each deployment platform** and whenever Python or a native dependency is upgraded. Record the tested interpreter, package lock, platform, and observed result in release/deployment evidence.

Do not bypass extension compatibility safeguards to force an import. Do not treat successful installation, import, or a green single-thread test as evidence of thread safety. If any required dependency or target platform is unsupported, keep the conventional-GIL runtime or select another parallelism strategy.
