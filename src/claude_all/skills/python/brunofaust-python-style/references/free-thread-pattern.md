# Free-Thread Pattern

The "free-thread" pattern in Python 3.14 typically refers to the use of `run_in_thread()` from the `core.thread_pool` module to handle blocking or I/O-bound operations within an async codebase, following the brunofaust-python-style conventions.

## When to Use
Use `run_in_thread()` when:
1. **Blocking I/O Operations**: For file operations, certain subprocess calls, or CPU-bound work that doesn't release the GIL.
2. **Legacy Sync Code**: When integrating with synchronous libraries that block the event loop.
3. **PEP 695 Generics**: Leveraging Python 3.14's enhanced type system with `async def` functions.

## Pros and Cons
### Pros:
- **Structured Concurrency**: Integrates with `asyncio.TaskGroup` for better error handling and cancellation.
- **Type Safety**: Works seamlessly with Pydantic v2 models.
- **Performance**: Reduces event loop blocking when used correctly.

### Cons:
- **Overhead**: Introduces threading overhead for simple operations.
- **Complexity**: Requires careful resource management (e.g., connection pools).
- **Debugging**: Thread-related issues (e.g., deadlocks) can be harder to trace.

## Implementation
### Basic Pattern
Use `core.thread_pool.run_in_thread()` to offload blocking work:

class MyService:
    async def safe_blocking_call(self, data: dict[str, Any]) -> str:
        """
        Performs a blocking operation safely using run_in_thread().
        """
        def _blocking_op(items: list[Any]) -> str:
            # Simulate blocking work
            time.sleep(0.1)
            return "Processed {len(items)} items"

        result = await core.thread_pool.run_in_thread(_blocking_op, data['items'])
        return result

### Error Handling
Wrap in try/except for thread-specific errors:
try:
    result = await core.thread_pool.run_in_thread(risky_operation, arg)
except core.thread_pool.ThreadError as e:
    logger.error("Thread error", exc_info=True)
    raise

## Checking Dependency Compatibility
1. **uv sync**: Ensure dependencies support Python 3.14
   ```bash
   uv sync --dev
   ```
2. **pip check**: Verify version compatibility
   ```bash
   pip check
   ```
3. **Runtime Check**:
   ```python
   import sys
   assert sys.version_info >= (3, 14), "Python 3.14+ required"
   ```
