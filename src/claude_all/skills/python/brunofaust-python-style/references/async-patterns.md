# Async + concurrency — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

## Async & Concurrency Patterns

Detailed async, threading, and concurrency patterns for production-grade async Python.
All patterns here are self-contained — they include full implementations so you can
create them from scratch in any project.

### When to Use

- **Everywhere**

### Core Concepts

The project is async-first, using:

- **ThreadPoolExecutor** for offloading blocking/CPU-bound work
- **asyncio.TaskGroup** or **asyncio.gather** for structured concurrency
- **asyncio.Semaphore** for concurrency limiting

### Best Practices Summary

1. **Use uvloop.run()** for entry point
1. **Always await coroutines** to execute them
1. **Limit concurrency with semaphores** - unbounded tasks can exhaust resources
1. **Implement proper error handling** with try/except
1. **Use timeouts** to prevent hanging operations
1. **Pool connections** for better performance
1. **Never block the event loop** - use `run_in_thread` for sync code
1. **Offload sync work only through `run_in_thread()`** — never call
   `asyncio.to_thread` directly. The wrapper is the single owner of the
   thread-offload seam (pool sizing, naming, leak tracking); a banned-api prek
   hook blocks raw `asyncio.to_thread`.
1. **Stay async-first — don't de-async a function just because it has no `await`.**
   The API is uniformly `async` so every call site stays awaitable; `RUF029`
   (async-method-without-await) is **ignored project-wide on purpose**. Reverting a
   function to sync to satisfy RUF029 is a regression, not a fix — don't do it.

### Event Loop Management

#### Entry Points

Never use `asyncio.run()` — always use uvloop for better performance.

```python
import asyncio
import uvloop


# Pattern 1: Lambda / simple script entry point
def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Entry point for AWS Lambda."""
    return uvloop.run(main(event=event))


# Pattern 2: Script with runner (reusable loop)
if __name__ == "__main__":
    with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
        runner.run(main(runner.get_loop()))
```

#### Loop Cleanup Callbacks

When your application creates resources that must be cleaned up when the event loop
shuts down (database connections, HTTP sessions, thread pools), you need a way to
register cleanup callbacks. Python's asyncio doesn't provide this natively, so we
build it.

The idea: wrap `loop.close()` so that registered async cleanup functions run (in
LIFO order) before the loop actually closes.

```python
"""
asyncio_loop.py — Event loop cleanup utilities.

Provides a way to register async cleanup callbacks that run when the
event loop closes. Useful for closing connections, shutting down pools,
and releasing resources in the correct order.
"""

import asyncio
import weakref
from collections.abc import Callable, Coroutine
from threading import RLock
from typing import Any


__all__ = ["wrap_loop_close", "register_loop_cleanup"]

# Track which loops have been wrapped (prevent double-wrapping)
wrapped_loops: weakref.WeakSet[asyncio.AbstractEventLoop] = weakref.WeakSet()

# Cleanup callbacks per loop: dict[loop_id, list[async_callable]]
cleanup_callbacks: dict[int, list[Callable[[], Coroutine[Any, Any, None]]]] = {}

# Thread-safe lock for modifying shared state
cleanup_lock = RLock()


def wrap_loop_close(loop: asyncio.AbstractEventLoop) -> bool:
    """
    Wrap loop.close() to execute registered cleanup callbacks first.

    This is idempotent — calling it on an already-wrapped loop is a no-op.
    Cleanup callbacks run in LIFO (reverse registration) order, which
    ensures that dependencies are cleaned up after their dependents.

    Args:
        loop: The event loop to wrap.

    Returns:
        True if the loop was newly wrapped, False if already wrapped.

    Examples:
        >>> loop = asyncio.get_running_loop()
        >>> wrap_loop_close(loop)
        True
        >>> wrap_loop_close(loop)  # idempotent
        False
    """
    with cleanup_lock:
        if loop in wrapped_loops:
            return False

        original_close = loop.close

        def _patched_close() -> None:
            loop_id = id(loop)
            callbacks = cleanup_callbacks.pop(loop_id, [])

            # Run cleanup callbacks in LIFO order
            for callback in reversed(callbacks):
                try:
                    # The loop is still running at this point
                    if loop.is_running():
                        loop.create_task(callback())
                    else:
                        loop.run_until_complete(callback())
                except Exception:
                    pass  # Best-effort cleanup

            original_close()

        loop.close = _patched_close  # type: ignore[method-assign]
        wrapped_loops.add(loop)

        # GC fallback: if the loop is garbage-collected without close()
        weakref.finalize(loop, lambda lid: cleanup_callbacks.pop(lid, None), id(loop))

        return True


def register_loop_cleanup(
    loop: asyncio.AbstractEventLoop,
    callback: Callable[[], Coroutine[Any, Any, None]],
    wrap_if_needed: bool = True,
) -> None:
    """
    Register an async cleanup callback that runs when the loop closes.

    Callbacks are executed in LIFO order (last registered = first to run).

    Args:
        loop: The event loop to register the callback on.
        callback: An async callable (no arguments) to run on cleanup.
        wrap_if_needed: If True, auto-wrap the loop if not already wrapped.

    Raises:
        RuntimeError: If the loop isn't wrapped and wrap_if_needed is False.

    Examples:
        >>> async def cleanup_db():
        ...     await db_pool.close()
        >>> register_loop_cleanup(loop, cleanup_db)
    """
    with cleanup_lock:
        if wrap_if_needed:
            wrap_loop_close(loop)
        elif loop not in wrapped_loops:
            raise RuntimeError("Loop is not wrapped. Call wrap_loop_close() first.")

        loop_id = id(loop)
        if loop_id not in cleanup_callbacks:
            cleanup_callbacks[loop_id] = []
        cleanup_callbacks[loop_id].append(callback)
```

**When to use this**: Register cleanup for any long-lived resource — AWS client sessions, database connection pools, HTTP client sessions, thread pool executors. The LIFO order means you can register the pool first, then connections that use the pool, and they’ll clean up in the correct order.

### Running Blocking Code in Threads (run_in_thread)

Many libraries (Polars, DeltaTable, file I/O) are synchronous and blocking.
Calling them directly in an async function blocks the entire event loop. The solution:
offload them to a thread pool.

#### Full Implementation

```python
"""
thread.py — Thread pool utilities for running blocking code in async contexts.

Provides run_in_thread() for offloading blocking work, and a thread class
for managing a dedicated ThreadPoolExecutor with result streaming.
"""

import asyncio
import inspect
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Final, ParamSpec, TypeVar, final

import uvloop

P = ParamSpec("P")
T = TypeVar("T")

# Global shared thread pool for blocking operations
BLOCKING_THREADPOOL: Final[ThreadPoolExecutor] = ThreadPoolExecutor(
    max_workers=10,
    thread_name_prefix="blocking-pool",
)


async def run_in_thread(
    func: Callable[P, T],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """
    Run a blocking function or coroutine in a thread pool.

    If func is a regular function, it runs directly in the thread pool.
    If func is a coroutine function, a new event loop is created in the
    worker thread to run it (isolated from the main loop).

    This is the primary way to call blocking libraries (Polars, DeltaTable,
    file I/O) from async code without blocking the event loop.

    Args:
        func: A sync function or async function to execute.
        *args: Positional arguments to pass to func.
        **kwargs: Keyword arguments to pass to func.

    Returns:
        The return value of func.

    Raises:
        Any exception raised by func.

    Examples:
        >>> # Blocking file read
        >>> data = await run_in_thread(Path("big_file.csv").read_text)

        >>> # Polars operation (blocking C extension)
        >>> df = await run_in_thread(pl.read_parquet, "s3://bucket/data.parquet")

        >>> # DeltaTable construction (blocking Rust FFI)
        >>> dt = await run_in_thread(DeltaTable, table_uri="s3://bucket/table")

        >>> # Async function that needs its own event loop
        >>> async def fetch_remote():
        ...     async with aiohttp.ClientSession() as session:
        ...         return await session.get("https://api.example.com")
        >>> result = await run_in_thread(fetch_remote)
    """
    loop = asyncio.get_running_loop()

    if inspect.iscoroutinefunction(func):
        # Async function → run in a new event loop inside a worker thread
        def _run_coro_isolated() -> T:
            new_loop = uvloop.new_event_loop()
            try:
                coro = func(*args, **kwargs)
                return new_loop.run_until_complete(coro)
            finally:
                new_loop.close()

        return await loop.run_in_executor(BLOCKING_THREADPOOL, _run_coro_isolated)
    else:
        # Sync function → run directly in thread pool
        import functools

        partial = functools.partial(func, *args, **kwargs)
        return await loop.run_in_executor(BLOCKING_THREADPOOL, partial)
```

#### Thread Pool Manager Class

For cases where you need a dedicated pool with result streaming:

```python
@final
class thread:
    """Thread pool manager for executing functions in separate threads.

    Provides a higher-level API over ThreadPoolExecutor with support for:
    - Running both sync and async callables
    - Waiting for all futures to complete
    - Streaming results as they become available

    Args:
        max_workers: Maximum number of concurrent threads.
        name_prefix: Thread name prefix for debugging.
        run_in_new_loop: If True, async callables get their own event loop.

    Examples:
        >>> pool = thread(max_workers=5, name_prefix="my-pool")
        >>> futures = []
        >>> for item in items:
        ...     futures.append(await pool.run(process_item, item))
        >>> done, pending = await pool.wait(futures)
        >>> pool.shutdown()
    """

    _thread_pool: ThreadPoolExecutor
    _run_in_new_loop: bool

    def __init__(
        self,
        max_workers: int = 5,
        name_prefix: str = "",
        run_in_new_loop: bool = True,
    ) -> None:
        self._thread_pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=name_prefix,
        )
        self._run_in_new_loop = run_in_new_loop

    async def run(self, func: Callable, *args: Any, **kwargs: Any) -> Future:
        """
        Submit a callable to the thread pool.

        Args:
            func: A sync or async callable.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            A Future representing the pending result.
        """
        if inspect.iscoroutinefunction(func):
            coro = func(*args, **kwargs)
            if self._run_in_new_loop:

                def _isolated() -> Any:
                    new_loop = uvloop.new_event_loop()
                    try:
                        return new_loop.run_until_complete(coro)
                    finally:
                        new_loop.close()

                return self._thread_pool.submit(_isolated)
            else:
                loop = asyncio.get_running_loop()
                # run_coroutine_threadsafe schedules the coroutine on the
                # running loop and returns a concurrent.futures.Future
                return asyncio.run_coroutine_threadsafe(coro, loop)
        else:
            import functools

            partial = functools.partial(func, *args, **kwargs)
            return self._thread_pool.submit(partial)

    async def wait(
        self,
        futures: list[Future],
        return_when: str = "ALL_COMPLETED",
    ) -> tuple[set[Future], set[Future]]:
        """Wait for futures to complete."""
        from concurrent.futures import wait

        return await run_in_thread(wait, futures, return_when=return_when)

    async def results(self, futures: list[Future]) -> AsyncIterator[Any]:
        """Yield results as futures complete (async generator)."""
        from concurrent.futures import as_completed

        for future in as_completed(futures):
            yield future.result()

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the thread pool."""
        self._thread_pool.shutdown(wait=wait)
```

#### When to Use run_in_thread

| Situation                              | Use run_in_thread?           |
| -------------------------------------- | ---------------------------- |
| Polars `.collect()`, `.sink_parquet()` | Yes — blocks on C extensions |
| DeltaTable construction, `.version()`  | Yes — blocks on Rust FFI     |
| `open()` / file I/O                    | Yes — blocks on disk I/O     |
| `polars.testing.assert_frame_equal`    | Yes — blocks on comparison   |
| Pure Python computation (< 1ms)        | No — overhead not worth it   |
| `await client.get_object(...)`         | No — already async           |

#### InterpreterPoolExecutor

`concurrent.futures.InterpreterPoolExecutor` (PEP 734, added in Python 3.14) is
available on the baseline — reach for it directly. Subinterpreters provide true
parallelism (each has its own GIL) with lower overhead than
`ProcessPoolExecutor`. Use it for **CPU-bound** work that doesn't need to share
mutable state.

```python
from concurrent.futures import InterpreterPoolExecutor


def compute_square(x: int) -> int:
    """CPU-bound computation."""
    return x * x


# Similar API to ThreadPoolExecutor / ProcessPoolExecutor
with InterpreterPoolExecutor() as executor:
    results = list(executor.map(compute_square, range(100)))
```

**When to use InterpreterPoolExecutor vs. run_in_thread:**

| Situation                                  | Use                                                    |
| ------------------------------------------ | ------------------------------------------------------ |
| CPU-bound pure Python (parsing, math)      | `InterpreterPoolExecutor` — true parallelism           |
| CPU-bound C extension (Polars, DeltaTable) | `run_in_thread` — C extensions already release the GIL |
| Blocking I/O (file, network)               | `run_in_thread` — simpler, lower overhead              |
| Needs shared mutable state                 | `run_in_thread` — interpreters are isolated            |

**Limitations**: Only picklable arguments/results. Shareable types without pickling
are limited to `str | bytes | int | float | bool | None | tuple | memoryview`.
C extensions that use global state may not work correctly across interpreters.

### Structured Concurrency with TaskGroup

#### Semaphore + TaskGroup Pattern

This is the most important concurrency pattern. It combines `asyncio.Semaphore` for
rate-limiting with `asyncio.TaskGroup` for structured concurrency (all tasks complete
or all fail together).

```python
async def batch_delete(
    self,
    table_name: str,
    keys: Sequence[Mapping[str, Any]],
    concurrency: int = 50,
) -> None:
    """
    Delete multiple items in parallel with concurrency control.

    Uses Semaphore + TaskGroup to limit concurrent API calls while
    ensuring all deletions complete (or fail atomically).

    Args:
        table_name: Target table name.
        keys: Items to delete.
        concurrency: Maximum concurrent delete operations.
    """
    parallel_semaphore = asyncio.Semaphore(concurrency)

    async with asyncio.TaskGroup() as tg:
        for chunk in batched(keys, 25):  # API batch limit
            tg.create_task(
                self._batch_delete_do(
                    parallel_semaphore=parallel_semaphore,
                    table_name=table_name,
                    items=chunk,
                )
            )


async def _batch_delete_do(
    self,
    parallel_semaphore: asyncio.Semaphore,
    table_name: str,
    items: Sequence[Mapping[str, Any]],
) -> None:
    """Single batch delete wrapped in semaphore."""
    async with parallel_semaphore:
        request = build_request(items)
        while True:
            response = await self._client.batch_write_item(RequestItems=request)
            unprocessed = response.get("UnprocessedItems", {})
            if not unprocessed or not unprocessed.get(table_name):
                break
            request = unprocessed  # Retry unprocessed items
```

#### Worker Function Naming Convention

Worker functions (the ones passed to `tg.create_task`) follow the `_name_do` suffix:

```python
# Public orchestrator — creates the TaskGroup, distributes work
async def process_items(items: Sequence[item_dtype], db: database_client) -> None:
    """Process all items in parallel with concurrency control."""
    parallel_semaphore = asyncio.Semaphore(10)
    async with asyncio.TaskGroup() as tg:
        for item in items:
            tg.create_task(_process_item_do(parallel_semaphore, item, db))


# Private worker — does the actual work for a single item
async def _process_item_do(
    parallel_semaphore: asyncio.Semaphore,
    item: item_dtype,
    db: database_client,
) -> None:
    """Process a single item (worker function)."""
    async with parallel_semaphore:
        await db.update(item)
```

#### Collecting Results from TaskGroup

```python
async def validate_items(
    items: Sequence[item_dtype],
    db: database_client,
    concurrency: int = 10,
) -> list[item_dtype]:
    """Validate items in parallel and return only valid ones."""
    parallel_semaphore = asyncio.Semaphore(concurrency)
    tasks: list[asyncio.Task[item_dtype | None]] = []

    async with asyncio.TaskGroup() as tg:
        for item in items:
            tasks.append(tg.create_task(_validate_item_do(parallel_semaphore, item, db)))

    # Collect results after TaskGroup completes (all tasks are done here)
    valid_items: list[item_dtype] = []
    for task in tasks:
        result = task.result()
        if result is not None:
            valid_items.append(result)

    return valid_items
```

#### TaskGroup Exception Handling with ExceptionGroup

When using `asyncio.TaskGroup`, if any task raises an exception, all remaining tasks
are cancelled and the exceptions are collected into an `ExceptionGroup`.
Use the `except*` syntax to handle them gracefully:

##### Alternative: Let ExceptionGroup Propagate

If you want the caller to decide how to handle failures:

```python
async def process_batch_strict(items: Sequence[item_dtype]) -> None:
    """Process batch — any failure cancels all tasks and raises."""
    async with asyncio.TaskGroup() as tg:
        for item in items:
            tg.create_task(_process_item_do(item))
    # If any task failed, ExceptionGroup propagates here
```

### Rollback Pattern

For operations that must be undone on failure:

```python
async def run_pipeline(event: dict[str, Any]) -> None:
    """Run pipeline with automatic rollback on failure."""
    rollback_info: dict[str, dict[str, Any]] = {}

    try:
        for entity in entities:
            # Track state before modification for rollback
            if (table := await get_table(entity)) is not None:
                rollback_info[entity] = {
                    "table_uri": table.table_uri,
                    "version": table.version(),
                }

            await transform_and_write(entity)

    except Exception as e:
        # Rollback all modified entities concurrently
        if rollback_info:
            parallel_semaphore = asyncio.Semaphore(10)
            async with asyncio.TaskGroup() as tg:
                for entity_name, info in rollback_info.items():
                    tg.create_task(_rollback_entity_do(parallel_semaphore, entity_name, info))
        raise


async def _rollback_entity_do(
    parallel_semaphore: asyncio.Semaphore,
    entity_name: str,
    info: dict[str, Any],
) -> None:
    """Rollback a single entity to its previous version."""
    async with parallel_semaphore:
        try:
            dt = DeltaTable(info["table_uri"], storage_options=info.get("storage_options", {}))
            dt.restore(info["version"])
            LOG.info(f"Rolled back {entity_name} to version {info['version']}")
        except Exception as e:
            LOG.warning(f"Rollback failed for {entity_name}: {type(e).__name__}-{e}")
```

### FIFO Queue Processing

For ordered processing within groups but parallel across groups:

```python
import asyncio
from collections import defaultdict


async def process_ordered_groups(
    groups: Mapping[str, Sequence[item_dtype]],
    concurrency: int = 10,
) -> None:
    """
    Process items per group in FIFO order, groups in parallel.

    Items within the same group are processed sequentially (preserving
    order), but different groups run concurrently.

    Args:
        groups: Mapping of group_id to ordered items.
        concurrency: Maximum concurrent groups.
    """
    queues: dict[str, asyncio.Queue[item_dtype]] = defaultdict(lambda: asyncio.Queue())

    for group_id, items in groups.items():
        for item in items:
            await queues[group_id].put(item)

    semaphore = asyncio.Semaphore(concurrency)
    async with asyncio.TaskGroup() as tg:
        for group_id, q in queues.items():
            tg.create_task(_group_worker_do(semaphore, group_id, q))


async def _group_worker_do(
    semaphore: asyncio.Semaphore,
    group_id: str,
    q: asyncio.Queue[item_dtype],
) -> None:
    """Process items from a single group's queue sequentially."""
    async with semaphore:
        while not q.empty():
            item = q.get_nowait()
            await process_item(item)
            q.task_done()
```

### Single-flight execution control (DynamoDB lock)

Stop a scheduled job from overlapping with its own in-flight run, dedup an
at-least-once SQS / Lambda-chain delivery, or serialise a critical section across
processes — all with **one DynamoDB table** and a conditional write. DynamoDB's
conditional `PutItem` is the cross-process compare-and-set primitive; no extra
infra (Redis, an SQS FIFO group) needed.

Two distinct jobs, two markers — don't conflate them:

- **Run-lock (mutual exclusion):** acquire *before* work, release in `finally`. A
  second invocation while the first is in flight fails the condition and **skips**
  (the cron fired again before the previous run finished).
- **Idempotency marker (exactly-once effect):** write *after* the side effect
  succeeds. A redelivery sees the marker and **no-ops**. Writing it *before* the
  effect would suppress a legitimate retry of a failed effect.

```python
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from botocore.exceptions import ClientError

LOCK_TTL_SECONDS = 15 * 60  # safety net if the holder dies without releasing


class LockHeld(Exception):
    """Another execution holds the lock — caller should skip, not retry."""


@asynccontextmanager
async def single_flight(table: "DDBTable", lock_id: str) -> AsyncIterator[None]:
    """Acquire a cross-process run-lock; skip if another run holds it.

    Acquire with a conditional ``PutItem`` (``attribute_not_exists``) so only one
    writer wins. ``expires_at`` lets a DynamoDB TTL reaper clear the lock if the
    holder crashes before ``finally`` runs. Released by ``DeleteItem``.

    Args:
        table: Owner wrapper around the lock table (see external-system-ownership).
        lock_id: Stable id of the *logical job*, not the trigger.

    Raises:
        LockHeld: the lock is already taken by an in-flight execution.
    """
    now = int(time.time())
    try:
        await table.put_item(
            Item={"pk": lock_id, "expires_at": now + LOCK_TTL_SECONDS},
            ConditionExpression="attribute_not_exists(pk) OR expires_at < :now",
            ExpressionAttributeValues={":now": now},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise LockHeld(lock_id) from exc
        raise
    try:
        yield
    finally:
        # Best-effort release; the TTL is the backstop if this never runs.
        await table.delete_item(Key={"pk": lock_id})
```

```python
# Scheduled dispatcher: never overlap the previous run.
try:
    async with single_flight(lock_table, "dispatcher"):
        await run_dispatch_cycle()
except LockHeld:
    logger.info("dispatch_skipped", reason="previous run in flight")
```

- **Enable the DynamoDB TTL** on `expires_at` so a crashed holder's lock
  self-clears — the `finally` release is the happy path, the TTL is the backstop.
- The condition `attribute_not_exists(pk) OR expires_at < :now` lets a *stale*
  lock be reclaimed; drop the `OR` clause if a stuck lock should instead require
  manual clearing.
- Same primitive behind EventBridge cron, an SQS consumer, or a Lambda chain — the
  lock is on the *logical job*, so the in-flight guard holds across all three.

### Async Pagination

For APIs that return paginated results:

```python
async def query_all(
    self,
    table_name: str,
    key: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """
    Query with automatic pagination.

    Follows pagination tokens until all results are collected.
    Each page's items are deserialized from the API format.

    Args:
        table_name: Table to query.
        key: Query key conditions.

    Returns:
        All matching items across all pages.
    """
    results: list[dict[str, Any]] = []
    last_key: dict[str, Any] | None = None

    while True:
        kwargs: dict[str, Any] = {"TableName": table_name}
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key

        response = await self._client.query(**kwargs)

        for row in response.get("Items", []):
            result = {k: await self._deserialize(v) for k, v in row.items()}
            results.append(result)

        if "LastEvaluatedKey" not in response:
            break
        last_key = response["LastEvaluatedKey"]

    return results
```

### Async Context Managers

Use `__aenter__` / `__aexit__` for resource lifecycle:

```python
class base_client:
    """Base async client with context manager support."""

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Async context manager exit — ensures proper cleanup."""
        await self.close()
```

Usage:

```python
async with storage_client() as client:
    await client.load()
    files = await client.get_items(bucket="my-bucket")
# Client automatically closed
```

### Common Semaphore Values

| Context                    | Value | Rationale                    |
| -------------------------- | ----- | ---------------------------- |
| Database batch operations  | 50    | Throughput limits            |
| File processing / logging  | 25    | Moderate parallelism         |
| API key validation         | 10    | Balance speed vs. throttling |
| Test resource creation     | 20    | Fast but safe for LocalStack  |
| General external API calls | 10    | Conservative default         |

### Lock ordering — one global acquisition order, always

Any transaction that takes locks on **more than one** row/table/resource — `SELECT ... FOR UPDATE`
across two tables, an advisory lock plus a row lock, two named advisory locks — must acquire them in a
**single documented global order**, and every path in the system must follow it. Two paths that lock
the same pair in *opposite* orders — one takes A then B, the other takes B then A — are a **lock-order
inversion**: path 1 holds A and waits for B, path 2 holds B and waits for A, and both block until a
timeout fires.

This is a production deadlock, not a theoretical one. Real incident: a **reserve** path locked the
wallet row then the ledger row, while a **settlement** path locked the ledger row then the wallet row.
Each worked in isolation and in every unit test; under concurrent load they deadlocked and stalled the
queue.

- **Pick one order and write it down** — e.g. "always lock `accounts` before `ledger_entries`;
  advisory locks by ascending key". Put it where the lock code lives.
- **Order is by a stable key, not by arrival.** When locking N rows of one table, `ORDER BY id` in
  the `SELECT ... FOR UPDATE` so concurrent transactions grab them in the same sequence.
- **Set a `lock_timeout`** so a mistake surfaces as a fast, logged error instead of an indefinite
  hang — a deadlock you can see beats one that just looks like "the queue is slow".

**The review question** — ask it of every multi-lock transaction:

> List every `FOR UPDATE` (and every advisory lock) in this transaction, in acquisition order. Does
> any *other* transaction take an overlapping set of the same locks in a **different** order?

If the answer is yes, that pair is a latent deadlock — reorder one path to match the global order.
There is no `async` escape from this: `asyncio` interleaves the two coroutines exactly the way two
threads or two connections would, so the ordering discipline is identical.
