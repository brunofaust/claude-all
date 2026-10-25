# Free-threaded Python 3.14 — optional deployment reference

Python 3.14's free-threaded CPython build can execute Python code on multiple
threads in parallel without the global interpreter lock (GIL). It is an optional
runtime target, not a change to this skill's Python 3.12+ language baseline. Keep
regular CPython as the supported default unless measured workload gains justify
an additional build, dependency, and deployment target.

## When to consider it

Evaluate free-threading when a service has substantial CPU-bound pure-Python work
that can be divided among threads, or when a workload has many concurrent threads
and profiling shows GIL contention. Prototype representative production work and
compare end-to-end throughput, tail latency, CPU, and memory against regular
CPython. Thread parallelism may simplify sharing in-process data compared with
process workers, but does not make shared mutable state safe.

Do not expect a benefit for I/O-bound async services, work already parallelized by
native libraries that release the GIL, or workloads limited by a database, network,
or another external service. Prefer the ordinary build if the free-threaded build
regresses performance, increases memory materially, lacks platform support, or
creates unacceptable dependency or operational risk. The GIL can be re-enabled at
runtime, including when an extension is incompatible, so confirm the mode rather
than assuming that a `t` build is actually running without it.

## Benefits and tradeoffs

Potential benefits:

- CPU-bound Python threads can run in parallel across cores, improving throughput
  without serializing work through a process pool.
- Existing thread-based designs may scale better when their work was limited by
  the GIL.
- Threads retain a shared address space, avoiding the serialization and data-copy
  costs of many process-based designs.

Costs and limitations:

- Speedups are workload-dependent; synchronization, allocator contention, and
  coordination can offset parallel execution. Free-threaded builds can use more
  memory and may be slower for single-threaded work.
- Every shared mutable object and native extension needs safe concurrent behavior.
  Correctness bugs may appear only under concurrent load.
- Some extension modules or wheels may be unavailable, incompatible, or may
  automatically re-enable the GIL. Build and deployment support varies by OS,
  architecture, and Python patch release.
- This is a separate runtime target to build, test, monitor, and support. It does
  not remove the need to bound concurrency or handle cancellation and failures.

## Select and verify the interpreter

Install a Python 3.14 free-threaded distribution for the target platform using the
project's supported runtime manager or official Python distribution. The free-
threaded ABI/build is commonly identified by a `t` suffix. Use the same pinned
Python patch version, OS, and architecture in local development, CI, and production.

Check both the build capability and active GIL state at startup or in diagnostics:

```python
import sys
import sysconfig

free_threaded_build = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
gil_enabled = sys._is_gil_enabled()
print(f"free-threaded build: {free_threaded_build}; GIL enabled: {gil_enabled}")
```

`sys._is_gil_enabled()` is a CPython-specific diagnostic; guard its use if the
same code must run on other implementations. The build flag only identifies the
build: importing an extension that does not declare free-threading support can
turn the GIL back on. Check the active state after importing the application's
full dependency stack. Treat an unexpected GIL-enabled state as a failed
free-threaded validation, not a successful benchmark.

The GIL can be controlled for diagnostics with `-X gil=0` or `PYTHON_GIL=0` on
supported CPython builds. Use these only deliberately: forcing it off can expose
unsafe extension behavior, and must not substitute for proving compatibility.

## Write and test thread-safe code

Free-threading does not guarantee atomicity for a sequence of operations. Do not
rely on incidental serialization by the GIL, including check-then-act patterns,
read-modify-write operations, iteration concurrent with mutation, or compound
updates across multiple objects. Protect invariants with `threading.Lock` or
`threading.RLock`, use thread-safe queues and synchronization primitives, or give
mutable state to one owner and communicate through messages. Prefer immutable
inputs/results and isolated worker state. Keep lock scope small, document lock
ordering when taking multiple locks, and avoid calling unknown code while holding
a lock.

Stress-test concurrent access and failure paths; tests that pass only under the
regular GIL are not evidence of safety. Bound worker counts and queues, measure
contention, and verify shutdown joins workers and releases resources. Asyncio
remains a single-event-loop concurrency model; free-threading does not make
asyncio objects safe to access from arbitrary threads. Use documented thread-safe
loop handoff mechanisms and keep event-loop-bound objects on their owning loop.

## Assess dependency compatibility

There is no universal approved-dependency list. Evaluate the exact, locked stack
for each target platform and Python 3.14 free-threaded build:

1. Check each dependency's current release notes, wheel availability, and
   documented free-threading support. Review native/C-extension and Rust
   components especially carefully. A successful installation alone does not
   establish support; package installers may fall back to a source build.
2. Create a clean environment with the target interpreter and install the
   project's locked dependencies using a recent installer that supports the
   free-threaded ABI. Record any source builds and the precise versions used.
3. Import the complete application and optional dependency paths, then check
   `sys._is_gil_enabled()` after imports. Investigate warnings or an enabled GIL;
   do not silently accept a fallback if parallel execution is the goal.
4. Run the full unit, integration, and end-to-end suites on this interpreter,
   including tests for races, shared caches, logging/context propagation, native
   libraries, shutdown, and cancellation. Add repeated stress runs for critical
   shared-state paths.
5. Benchmark representative workloads under comparable regular and free-threaded
   builds. Compare correctness, throughput, latency, peak memory, CPU, and
   operational behavior; retain the regular build if the measured benefit does
   not outweigh the extra support cost.
6. Deploy gradually with an easy rollback to the regular build. Monitor active
   GIL state, errors, latency, resource use, and throughput; re-evaluate after
   upgrading Python or any dependency that includes native code.

A dependency's claim of support is a useful screening signal, not a substitute
for testing the exact versions and execution paths used by the application.
