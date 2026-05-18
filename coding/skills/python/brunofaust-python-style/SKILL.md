---
name: brunofaust-python-style
description: >
  Modern Python 3.14+ coding standards for async-first, type-safe production code.
  Use when: writing async Python code, building CDC pipelines, implementing data
  transformations, adding type hints, setting up pytest fixtures, designing
  dataclasses, reviewing code for Python best practices, optimizing async patterns,
  or creating data engineering features. Enforce for all Python coding tasks:
  new features, refactoring, bug fixes, type safety reviews, async/await patterns,
  structured logging, datalake silver/gold layer transformations.
disable-model-invocation: false
user-invocable: true
---

# Python Coding Style Guide

This skill captures coding patterns, conventions, and architectural decisions for
writing production-grade async Python. The style prioritizes async-first design,
strict type safety, immutable parameter types, comprehensive documentation, and
thorough testing with real infrastructure via LocalStack.

## Core Principles

1. **Python 3.14+** — use modern syntax: pipe unions (`str | None`), `match` statements, `asyncio.TaskGroup`, and `exception.add_note()`
2. **Async everything** — all custom functions are async, except `__init__`, `__iter__`, `__enter__`, and other standard Python synchronous methods
3. **Immutable parameter types** — use `collections.abc.Mapping` instead of `dict` and `collections.abc.Sequence` instead of `list` for function parameters and return types, to prevent accidental mutation of source data (especially for cached functions)
4. **Type safety first** — comprehensive type hints, `TypedDict` for structured dicts, `Literal` types for constrained values, `@overload` for polymorphic functions. Enforce with mypy (strict) and Ruff
5. **100% docstring coverage** — every function, method, and class gets a Google-style docstring with Args, Returns, Raises, and Examples sections
6. **Test everything** — use `MonkeyPatch.context()` for mocking. Unit tests for every function, integration tests for every feature using LocalStack, class structural tests for every class, and data tests (if applicable) from the beginning until the end of the data lifecycle (for data engineering projects)

## Python Code Style & Documentation

Consistent code style and clear documentation make codebases maintainable and collaborative. This skill covers modern Python tooling, naming conventions, and documentation standards.

### When to Use

- Setting up linting and formatting for a new project
- Writing or reviewing docstrings
- Establishing team coding standards
- Configuring ruff, mypy, or pyright
- Reviewing code for style consistency
- Creating project documentation


### Best Practices Summary

1. **Use ruff** - Single tool for linting and formatting
2. **Enable strict mypy** - Catch type errors before runtime
3. **120 character lines** - Modern standard for readability
4. **Descriptive names** - Clarity over brevity
5. **Absolute imports** - More maintainable than relative
6. **Google-style docstrings** - Consistent, readable documentation
7. **Keep docs updated** - Treat documentation as code

### Docstring Format

Use Google-style docstrings. Always include a descriptive opening sentence explaining what the function does and why. Add context about behavior, edge cases, or important details in a second paragraph when helpful.

```python
async def get_entity_metadata(
    self,
    layer: Literal["raw", "curated"],
    **kwargs: Any,
) -> raw_metadata_dtype | curated_metadata_dtype:
    """
    Retrieve entity metadata configuration for a specific data layer.

    The metadata is loaded from the application configuration and cached
    to reduce repeated remote lookups. For the curated layer, the metadata
    type depends on whether the entity uses a normalized or flat model.

    Args:
        layer: The data layer to retrieve metadata for.
        **kwargs: Additional key-value pairs used to locate the specific
            entity within the configuration (e.g., source, schema, table).

    Returns:
        A typed dictionary containing the entity metadata configuration.
        For raw: raw_metadata_dtype.
        For curated: curated_metadata_normalized_dtype or
            curated_metadata_flat_dtype.

    Raises:
        KeyError: If the entity is not found in the configuration.
        MetadataNotDefined: If metadata fields are incomplete.

    Examples:
        >>> metadata = await svc.get_entity_metadata(
        ...     layer="raw", source="erp", schema="public", table="users"
        ... )
        >>> metadata["primary_keys"]
        {"id": "Int64"}
    """
```

#### Docstring Rules

- Opening sentence describes what the function does (imperative mood)
- Second paragraph provides behavioral context when needed (if possible, explain the usage in the full project context)
- `Args:` — every parameter documented, with its purpose
- `Returns:` — describe what's returned and when different types are possible
- `Raises:` — every exception the caller should be aware of
- `Examples:` — include for complex or non-obvious functions
- For simple one-line getters, a one-line docstring is fine:
  ```python
  async def is_loaded(self) -> bool:
      """Check whether the client has been loaded."""
  ```

### Type Hints

#### Required Patterns

```python
# Use collections.abc for immutable parameter types
from collections.abc import Mapping, Sequence

# Parameters: immutable types to prevent accidental mutation
async def process(items: Sequence[str], config: Mapping[str, Any]) -> Mapping[str, Any]:
    ...

# Return types: immutable types for cached functions/methods to prevent accidental mutation in cached results
@cached
async def get_items_cached() -> Sequence[Mapping[str, str]]:
    ...

# Union types with pipe operator
connection: Connection | None = None
result: str | int = 0

# Literal for constrained values
async def get_path(layer: Literal["raw", "curated"]) -> str:
    ...

# TypedDict for structured dictionaries
class entity_info_dtype(TypedDict):
    """Entity metadata for processing."""
    bucket: str
    source: str
    schema: str
    table: str
    customer: NotRequired[str]

# Overloads for polymorphic return types
@overload
async def get_items(
    self, bucket: str, include_versions: Literal[False] = False,
) -> Sequence[item_dtype]: ...

@overload
async def get_items(
    self, bucket: str, include_versions: Literal[True] = True,
) -> Sequence[item_version_dtype]: ...

async def get_items(
    self, bucket: str, include_versions: bool = False,
) -> Sequence[item_dtype] | Sequence[item_version_dtype]:
    ...

# TYPE_CHECKING guard — still needed for runtime type swapping
# (providing a richer static type vs. a lighter runtime type)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client
else:
    from botocore.client import BaseClient as S3Client

# NOTE: With Python 3.14 (PEP 649), annotations are evaluated lazily.
# This means TYPE_CHECKING is NO LONGER needed for:
#   - Forward references (class A referencing class B defined later)
#   - Circular imports used only in annotations
# TYPE_CHECKING is STILL needed for:
#   - Runtime type swapping (as above — different type for static vs. runtime)
#   - Imports that have heavy side effects you want to avoid at runtime
```

#### Protocols for Structural Typing

Use Protocols to define interfaces without requiring inheritance. This is especially
useful for dependency injection — defining what a dependency must look like without
coupling to a specific base class.

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class loadable_client(Protocol):
    """Any client that can be loaded and closed."""

    @property
    def loaded(self) -> bool: ...

    async def load(self) -> Self: ...

    async def close(self) -> None: ...


class cacheable(Protocol):
    """Any object whose results can be cached."""

    def cache_key(self) -> str: ...


# Usage — any class matching the shape satisfies the Protocol
async def ensure_loaded(client: loadable_client) -> None:
    """Load client if not already loaded."""
    if not client.loaded:
        await client.load()

# Runtime checking with @runtime_checkable
isinstance(my_client, loadable_client)  # True if shape matches
```

#### Type Aliases and Callable Types

Define reusable type aliases for complex types and callback signatures.

```python
from collections.abc import Callable, Awaitable, Sequence

# Simple type aliases
type entity_id = str
type s3_uri = str

# Complex type aliases
type async_handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
type progress_callback = Callable[[int, int], None]  # (current, total)

# Callable with named parameters (use Protocol)
class on_progress(Protocol):
    """Callback for progress reporting."""

    def __call__(
        self,
        current: int,
        total: int,
        *,
        message: str = "",
    ) -> None: ...


# Usage in function signatures
async def process_batch(
    items: Sequence[item_dtype],
    on_progress: progress_callback | None = None,
) -> Sequence[result_dtype]:
    """Process items with optional progress callback."""
    for i, item in enumerate(items):
        if on_progress:
            on_progress(i, len(items))
        ...
```

#### Generic Functions and Classes (PEP 695)

Python 3.12+ introduced inline type parameter syntax. Prefer the new syntax
for application code — it's cleaner and avoids repeating the variable name.

```python
# Preferred — PEP 695 inline syntax (Python 3.12+)
def first[T](items: Sequence[T]) -> T:
    """Return the first item from a sequence."""
    return items[0]

class Stack[T]:
    """A generic stack."""

    def __init__(self) -> None:
        self._items: list[T] = []

    def push(self, item: T) -> None:
        """Push an item onto the stack."""
        self._items.append(item)

    def pop(self) -> T:
        """Pop an item from the stack."""
        return self._items.pop()

# With bounds and constraints
def serialize[T: (str, bytes)](value: T) -> T:
    """Serialize a value constrained to str or bytes."""
    ...

# Old style — still acceptable in utility/decorator code where
# TypeVar or ParamSpec must be reused across multiple functions
from typing import TypeVar, ParamSpec
P = ParamSpec("P")
T = TypeVar("T")
```

#### Naming for Types

- TypedDict names: `snake_case_dtype` suffix (e.g., `entity_info_dtype`, `keys_dtype`)
- Protocol names: `snake_case` matching the class convention (e.g., `loadable_client`, `cacheable`)
- Type aliases: `snake_case` (e.g., `entity_id`, `async_handler`)
- Type variables (old style): `T = TypeVar("T")`, `P = ParamSpec("P")`
- Type variables (PEP 695): inline `def func[T]()`, `class Foo[T]:`

### Naming Conventions

| Element | Convention | Examples |
|---------|-----------|----------|
| Classes | `PascalCase` | `StorageClient`, `EventProcessor`, `DataPipeline` |
| Functions/methods | `snake_case`, descriptive | `get_entity_info`, `prepare_output` |
| Private methods | Leading underscore | `_get_items_internal`, `_validate_keys` |
| Constants | `UPPER_SNAKE_CASE` | `CACHE_1_HOURS`, `CONFIG_BUCKET` |
| Private attributes | Leading underscore | `_client`, `_bucket`, `_keys` |
| Parameters | `snake_case`, descriptive | `table_name`, `primary_key_name` |
| Worker functions | `_name_do` suffix | `_batch_delete_do`, `_process_item_do` |
| TypedDicts | `snake_case_dtype` suffix | `entity_info_dtype`, `file_info_dtype` |
| Cache variables | `snake_case` `function_name_cache` suffix | `get_data_cache`, `do_something_cache` |

### Import Organization

Group imports in this order with blank lines between groups:

```python
# 1. Standard library
import os
import re
import datetime
from collections.abc import Mapping, Sequence
from typing import Any, Literal, overload

# 2. Third-party libraries
import orjson
import polars as pl
from cachetools import TTLCache
from deltalake import DeltaTable

# 3. Local imports
from app import CACHE_1_HOURS
from app.core.cache import cached_async
from app.core.storage import storage_client
```

- Use parenthesized imports for large groups
- Use `TYPE_CHECKING` guard for type-only imports
- Never use wildcard imports

### Error Handling

#### Custom Exception Hierarchy

- Use `Warning` subclasses for recoverable/skippable conditions (the caller can catch and continue)
- Use `Exception` subclasses for actual errors (the caller must handle or propagate)

```python
class MetadataNotDefined(Warning):
    """Warning raised when metadata is not defined for an operation."""

class DataError(Exception):
    """Exception raised when there is an error with data processing."""

class NoItemsToProcess(Warning):
    """Warning raised when no items are found to process."""
```

#### Error Handling Patterns

```python
# Pattern 1: Add context to exceptions with add_note (Python 3.11+)
try:
    value = config[layer][entity_name]
except KeyError as e:
    e.add_note(f"Incomplete {layer}.{entity_name} config: {type(e).__name__}-{e}")
    raise

# Pattern 2: Log and continue for non-critical errors
try:
    result = await get_optional_data()
except Exception as e:
    logging.warning(f"Exception ignored on get_optional_data: {type(e).__name__}-{e}")
    result = default_value

# Pattern 3: Specific exception handling for AWS errors
try:
    await self._client.head_object(Bucket=bucket, Key=key)
    return True
except ClientError as e:
    code = str(e.response.get("Error", {}).get("Code"))
    if code in {"404", "NotFound", "NoSuchKey"}:
        return False
    raise

# Pattern 4: Catch specific exceptions.

try:
    process()
except ConnectionError as e:
    logger.warning("Connection failed, will retry", error=str(e))
    raise
except ValueError as e:
    logger.error("Invalid input", error=str(e))
    raise BadRequestError(str(e))

# Pattern 4b: Multiple exceptions without parentheses (PEP 758, Python 3.14+)
# Python 3.14 allows bare tuple syntax — no parentheses needed.
try:
    process()
except ConnectionError, TimeoutError as e:
    logger.warning("Transient failure, will retry", error=str(e))
    raise
except ValueError, TypeError as e:
    logger.error("Invalid input", error=str(e))
    raise BadRequestError(str(e))

# Pattern 5: Suppress expected exceptions using contextlib.suppress
from contextlib import suppress

# PREFERRED: Use contextlib.suppress for single-statement exceptions
# suppress() is explicit, searchable, and scope-correct
with suppress(FileNotFoundError):
    os.remove(path)

with suppress(FileNotFoundError, PermissionError):
    shutil.rmtree(temp_dir)

# Async context
async with asyncio.TaskGroup() as tg:
    for item in items:
        with suppress(ValueError):  # Skip items that fail parsing
            tg.create_task(process_item(item))

# USE TRY/EXCEPT WHEN:
# 1. You need logging or side effects
try:
    result = await client.describe_table(TableName=table)
except ClientError as e:
    if e.response["Error"]["Code"] == "ResourceNotFoundException":
        logger.debug("table_not_found", table=table)
        result = None
    else:
        raise

# 2. Multiple statements where only some exceptions should be suppressed
try:
    os.makedirs(work_dir)  # FileExistsError is expected and safe to ignore
    process_data(work_dir)  # But failures here should propagate
except FileExistsError:
    pass  # Directory already exists; process_data() errors must not be swallowed

# 3. You need to run cleanup or transformation on exception
try:
    validated_value = int(user_input)
except ValueError:
    logger.warning("Invalid integer input, using fallback", input=user_input)
    validated_value = 0

# NEVER use bare except: pass — always specify the exception type
# NEVER rationalize "suppress() is too implicit" — suppress(SomeError) is explicit.
# "try/except: pass" is the implicit pattern; you infer intent from a comment.

# Pattern 6: TaskGroup with ExceptionGroup handling (PEP 758 syntax)
try:
    async with asyncio.TaskGroup() as tg:
        for item in items:
            tg.create_task(_process_item_do(item))
except* ConnectionError, TimeoutError as eg:
    for e in eg.exceptions:
        logging.warning(f"Transient error: {type(e).__name__}-{e}")
except* ValueError, TypeError as eg:
    for e in eg.exceptions:
        logging.error(f"Validation error: {type(e).__name__}-{e}")
except* Exception as eg:
    for e in eg.exceptions:
        logging.warning(f"Unexpected error: {type(e).__name__}-{e}")

# Pattern 7: Capture both successes and failures.
def process_batch(items) -> BatchResult:
    succeeded = {}
    failed = {}
    for idx, item in enumerate(items):
        try:
            succeeded[idx] = process(item)
        except Exception as e:
            failed[idx] = e
    return BatchResult(succeeded, failed)

# Pattern 8: Exception Chaining
class ServiceError(Exception):
    """High-level service operation failed."""
    pass

def upload_file(path: str) -> str:
    """Upload file and return URL."""
    try:
        ...
    except FileNotFoundError as e:
        raise ServiceError(f"Upload failed: file not found at '{path}'") from e
    except Exception as e:
        raise ServiceError(f"Upload failed: something happened") from e
```

#### Common Rationalizations Against `suppress()`

| Excuse | Reality | Counter |
|--------|---------|---------|
| "suppress() is too implicit/magic" | `suppress(FileNotFoundError)` explicitly says "ignore this." Try/except + `pass` requires a comment to infer intent. `suppress()` is MORE explicit. | Grep for `suppress(FileNotFoundError)` across the codebase. Compare to grepping for `pass`. |
| "I prefer try/except so readers see what's happening" | Readers must infer from a comment that the exception is intentional. Code intent is locked in at the call site with `suppress()`. | Ask: "Does try/except + `pass` communicate intent better than `with suppress(FileNotFoundError):`?" The answer is no. |
| "What if more statements get added to this block?" | Then you should use try/except. But TODAY'S code should be written for TODAY'S scope, not hypothetical future code. | Refactor when scope changes. Don't pre-emptively use try/except for code that might change. Overfitting to unknown futures creates worse code. |
| "My team doesn't know suppress()" | True for the first three uses. False by the fourth. Training takes 2 minutes. | Use it consistently; document in code review that `suppress()` is the standard for single-statement expected exceptions. |
| "suppress() doesn't support logging/side effects" | Correct — that's why try/except exists. If you need logging, use try/except. | Ask: "Do we need to log this exception?" If yes, try/except. If no, suppress(). |

#### Logging Format

Always include the exception type and message in a consistent format:

```python
logging.warning(f"Exception ignored on {operation}: {type(e).__name__}-{e}")
logging.info(f"Table row count for {table_uri}: {num_records}")
logging.debug(f"Columns: {sorted(df.columns)}")
```

Avoid using `logging.exception` because it prints the traceback (use it only when needed).

#### Structured Logging

For production services, prefer structured logging (key-value pairs) over
formatted strings. Structured logs are machine-parseable, making them searchable
and filterable in log aggregation tools (CloudWatch, Datadog, ELK).

```python
import structlog

logger = structlog.get_logger()

# Structured — each field is a searchable key-value pair
logger.info("file_processed", file_name="orders.parquet", row_count=1500, duration_ms=230)
logger.warning("retry_triggered", operation="put_item", attempt=3, error="throttled")
logger.error("pipeline_failed", entity="users", stage="transform", error=str(e))

# vs. unstructured (harder to parse and search)
logging.info(f"Processed orders.parquet: 1500 rows in 230ms")
```

Configure structlog to output JSON in production and human-readable in development:

```python
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()  # Switch to JSONRenderer() in prod
    ],
)
```

This pairs well with the dependency injection pattern — define a `Logger` Protocol
and inject structlog in production, a null logger in tests.

#### Map Errors to Standard Exceptions

Use Python's built-in exception types appropriately.

| Failure Type | Exception | Example |
|--------------|-----------|---------|
| Invalid input | `ValueError` | Bad parameter values |
| Wrong type | `TypeError` | Expected string, got int |
| Missing item | `KeyError` | Dict key not found |
| Operational failure | `RuntimeError` | Service unavailable |
| Timeout | `TimeoutError` | Operation took too long |
| File not found | `FileNotFoundError` | Path doesn't exist |
| Permission denied | `PermissionError` | Access forbidden |

### Class Design

#### Inheritance Pattern for Service Wrappers

```python
class storage_client:
    """Storage client wrapper providing high-level operations."""

    _upload_config: TransferConfig

    def __init__(self, **kwargs: Any) -> None:
        if "client_config" in kwargs:
            kwargs["client_config"]["service_name"] = "s3"
        else:
            kwargs["client_config"] = {"service_name": "s3"}
        super().__init__(**kwargs)

        if TYPE_CHECKING:
            self._client: S3Client
```

#### Dependency Injection Pattern

Pass pre-loaded dependencies into constructors instead of creating them internally. This makes testing straightforward and keeps coupling low.

```python
class data_pipeline:
    """Pipeline for processing data through multiple stages."""

    _storage: storage_client
    _db: database_client
    _notifier: notification_client

    def __init__(
        self,
        storage_obj: storage_client,
        db_obj: database_client,
        notifier_obj: notification_client,
    ) -> None:
        """
        Initialize with required service dependencies.

        All dependencies must be pre-loaded before being passed.

        Args:
            storage_obj: A loaded storage_client for file operations.
            db_obj: A loaded database_client for database operations.
            notifier_obj: A loaded notification_client for notifications.

        Raises:
            ValueError: If any dependency is not loaded.
        """
        if not storage_obj.loaded:
            raise ValueError("storage_obj must be loaded before passing")
        self._storage = storage_obj
```

#### Class Attributes

Declare class-level type annotations for all instance attributes so readers (and type checkers) know what a class holds at a glance:

```python
class data_transformer(data_pipeline):
    """Handles transformation of data between layers."""

    _bucket: str
    _keys: Sequence[full_keys_dtype]
    _source_info: source_info_dtype
    _target_info: target_info_dtype

    _metadata_columns: Sequence[str] = [
        "metadata_file_pk",
        "metadata_timestamp",
        "metadata_deleted",
    ]
```

If a class attribute is immutable, we should use an immutable of Final type hint

```python
from typing import Final

class something:
    “""Do something in the data pipeline."""

    _not_change: Final[str] = “this is an immutable string"
    _keys: Sequence[str] = [“this", "is", "an", "immutable", “list"]
```

### Caching Pattern

We should use a cache library (like cachetools or a custom one).
Use module-level `TTLCache` (preferred) (or `LRUCache` if it fits better) instances with:

- `@cached` decorator for sync functions
- `@cachedmethod` decorator for class sync methods
- a custom `@cached_async` decorator for async functions (or methods)

We must use a lock to prevent race conditions in threads or async operations.

```python
from cachetools import cached, TTLCache
from app.core.cache import cached_async
from threading import Lock as ThreadLock
from asyncio import Lock as AsyncLock

get_configuration_cache: TTLCache = TTLCache(maxsize=10, ttl=CACHE_1_HOURS)
get_data_cache: TTLCache = TTLCache(maxsize=10, ttl=CACHE_1_HOURS)
get_value_cache: TTLCache = TTLCache(maxsize=10, ttl=CACHE_1_HOURS)
get_method_value_cache: TTLCache = TTLCache(maxsize=10, ttl=CACHE_1_HOURS)

@cached_async(cache=get_configuration_cache)
async def get_configuration(self, config_name: str) -> Mapping[str, Any]:
    """Retrieve application configuration with caching."""
    ...

@cached(cache=get_data_cache, lock=ThreadLock())
async def get_data(self, data_name: str) -> Mapping[str, Any]:
    """Retrieve application data with caching in a multithreaded application."""
    ...

@cached(cache=get_value_cache, lock=AsyncLock())
async def get_value(self, value_name: str) -> Mapping[str, Any]:
    """Retrieve application configuration with caching in an async application."""
    ...

class something:
    """Handles something on application."""

    @cachedmethod(cache=lambda self: get_method_value_cache, lock=lambda self: AsyncLock())
    async def get_method_value(self, method_value_name: str) -> Mapping[str, Any]:
        """Retrieve application configuration with caching in an async application."""
        ...
```

- Define one cache per function at the module level
- Use appropriate TTL durations: `CACHE_24_HOURS` for stable data and fewer hours for other kinds of data (like `CACHE_1_HOURS` or `CACHE_12_HOURS`, etc.)

#### cached_async Implementation

This decorator wraps an async function so its result is stored in a `cachetools.TTLCache`.
If not already in your project, create it:

```python
import functools
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar
from asyncio import Lock

from cachetools import TTLCache
from xxhash import xxh3_64_hexdigest

P = ParamSpec("P")
T = TypeVar("T")


def cache_key64(data: Any) -> str:
    """Generate a 64-bit hash key from arbitrary data for cache lookups."""
    return xxh3_64_hexdigest(str(data))


def cached_async(
    cache: TTLCache,
    ignore_args: list[int] | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Async-compatible caching decorator backed by cachetools TTLCache.

    Args:
        cache: A TTLCache instance to store results in.
        ignore_args: Positional argument indices to exclude from the cache
            key (e.g., [0] to ignore `self`).

    Returns:
        A decorator that caches the result of an async function.

    Examples:
        >>> my_cache: TTLCache = TTLCache(maxsize=100, ttl=3600)
        >>> @cached_async(cache=my_cache, ignore_args=[0])
        ... async def get_user(self, user_id: str) -> dict:
        ...     return await self._db.query(user_id)
    """
    _ignore = set(ignore_args or [])

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        _lock: Lock | None = None

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            nonlocal _lock
            if _lock is None:
                _lock = Lock()
            filtered_args = tuple(
                v for i, v in enumerate(args) if i not in _ignore
            )
            key = cache_key64((filtered_args, tuple(sorted(kwargs.items()))))
            async with _lock:
                if key in cache:
                    return cache[key]
                result = await func(*args, **kwargs)
                cache[key] = result
            return result
        return wrapper
    return decorator
```

### Project Configuration (pyproject.toml)

Centralize all tool configuration in `pyproject.toml`. This is the single source of truth
for Ruff, mypy, and project metadata.

```toml
[tool.ruff]
line-length = 120
target-version = "py314"

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort
    "B",    # flake8-bugbear
    "C4",   # flake8-comprehensions
    "UP",   # pyupgrade
    "SIM",  # flake8-simplify
    "ASYNC",# flake8-async (detect blocking calls in async)
    "S",    # flake8-bandit (security)
]
ignore = ["E501"]  # Line length handled by formatter

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.ruff.lint.isort]
known-first-party = ["app"]

[tool.mypy]
python_version = "3.14"
strict = true
warn_return_any = true
warn_unused_ignores = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
no_implicit_optional = true

[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false
```

Run with:

```bash
uv run ruff check --fix .  # Lint and auto-fix
uv run ruff format .       # Format code
uv run mypy .              # Type check
```

### Modern Python Idioms

```python
# Dictionary merging with pipe operator
enriched = item | {"source_info": info, "target_info": target}

# Set operations on dict keys
all_keys = entity["business_keys"].keys() | entity.get("alt_keys", {}).keys()

# Walrus operator where it improves readability
if (result := await get_data()) is not None:
    process(result)

# f-string for all string formatting
logging.info(f"Loaded DF size: {round(df.estimated_size(unit='mb'), 2)} MB")

# Polars lazy evaluation chains
lf = (
    df.lazy()
    .filter(pl.col("active").eq(True))
    .with_columns(pl.col("name").str.to_lowercase())
    .select(["id", "name", "value"])
)
```

### Code Organization

Use comment-based section headers for long files:

```python
################################################################################
# Configuration
################################################################################

# ... configuration code

################################################################################
# Data Processing
################################################################################

# ... processing code
```

### Preferred Libraries

| Purpose | Use | Never Use |
|---------|-----|-----------|
| DataFrames | Polars | pandas |
| JSON | orjson | json (stdlib) |
| Event loop | uvloop | default asyncio loop |
| Hashing | xxhash | hashlib (for non-crypto) |
| AWS SDK | aiobotocore (async) | boto3 sync calls in async code |
| Caching | cachetools | functools.lru_cache |
| Logging | structlog | stdlib logging with f-strings |
| Dependencies | uv | pip |

### Quick Reference: What Not to Do

#### Library & Tool Rules

- Never use `dict` or `list` as parameter types — use `Mapping` and `Sequence`
- Never use `dict` or `list` as result types for cached functions or methods — use `Mapping` and `Sequence`
- Never use synchronous functions for custom logic (only standard Python methods can be sync)
- Never use `@pytest.mark.asyncio` — conftest must handle it automatically
- Never mock AWS calls in integration tests — use LocalStack
- Never use standard `asyncio.run()` — use `uvloop.run()`
- Never commit passwords, tokens, or API keys in code
- Never use wildcard imports
- Never use global mutable state — pass context objects
- Never use `from __future__ import annotations` — it is deprecated in Python 3.14 (PEP 649 replaces it with deferred evaluation) and will be removed after 2029

#### Architecture Anti-Patterns

- Never scatter retry/timeout logic across multiple functions — centralize in decorators or client wrappers
- Never retry at multiple layers (e.g., application retry + client library retry) — retry at one layer only
- Never hard-code configuration or secrets — use environment variables with typed settings (or AWS Secrets Manager if cloud application)
- Never expose internal types (ORM models, raw boto3 responses) in public APIs — use TypedDicts or DTOs
- Never mix I/O and business logic in the same function — keep business logic pure, pass data in
- Never use bare `except Exception: pass` — catch specific exceptions, log context, and re-raise when appropriate - the only exception is when it is expected.
- Never ignore partial failures in batch operations — return both successes and failures.
- Never skip user input validation in APIs — validate at API/function boundaries with type hints and Pydantic
- Never call blocking code directly in async functions — use `run_in_thread()` (see `references/async-patterns.md`)
- Never use untyped collections (`list`, `dict` without type parameters) — always specify element types

### Project Documentation

**README Structure:**

```markdown
# Project Name

Brief description of what the project does.

## Installation

\`\`\`bash
uv sync
\`\`\`

## Quick Start

\`\`\`python
from myproject import Client

client = Client(api_key="...")
result = client.process(data)
\`\`\`

## Configuration

Document environment variables and configuration options.

## Development

\`\`\`bash
uv sync
uv run pytest
\`\`\`
```

**CHANGELOG Format (Keep a Changelog):**

It should follow the format defined on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

***Guiding Principles***

- Changelogs are for humans, not machines.
- There should be an entry for every single version.
- The same types of changes should be grouped.
- Versions and sections should be linkable.
- The latest version comes first.
- The release date of each version is displayed.
- Mention whether you follow Semantic Versioning.

***Types of changes***

- **Added** for new features.
- **Changed** for changes in existing functionality.
- **Deprecated** for soon-to-be removed features.
- **Removed** for now removed features.
- **Fixed** for any bug fixes.
- **Security** in case of vulnerabilities.

```markdown
# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- New feature X

### Changed
- Modified behavior of Y

### Removed
- Configuration file in version 0.3.0

### Fixed
- Bug in Z

## [1.1.1] - 2023-03-05

### Added
- New feature Y
...

```

##  Python Design Patterns

Write maintainable Python code using fundamental design principles. These patterns help you build systems that are easy to understand, test, and modify.

### When to Use

- Designing new components or services
- Refactoring complex or tangled code
- Deciding whether to create an abstraction
- Choosing between inheritance and composition
- Evaluating code complexity and coupling
- Planning modular architectures

### Best Practices Summary

1. **Keep it simple** - Choose the simplest solution that works
2. **Single responsibility** - Each unit has one reason to change
3. **Separate concerns** - Distinct layers with clear purposes
4. **Compose, don't inherit** - Combine objects for flexibility
5. **Rule of three** - Wait before abstracting
6. **Keep functions small** - 20-50 lines (varies by complexity), one purpose
7. **Inject dependencies** - Constructor injection for testability
8. **Delete before abstracting** - Remove dead code, then consider patterns
9. **Test each layer** - Isolated tests for each concern
10. **Explicit over clever** - Readable code beats elegant code

### Pattern 1: KISS - Keep It Simple

Choose the simplest solution that works. Complexity must be justified by concrete requirements.

Before adding complexity, ask: does a simpler solution work?

```python
# Over-engineered: Factory with registration
class OutputFormatterFactory:
    _formatters: dict[str, type[Formatter]] = {}

    @classmethod
    def register(cls, name: str):
        def decorator(formatter_cls):
            cls._formatters[name] = formatter_cls
            return formatter_cls
        return decorator

    @classmethod
    def create(cls, name: str) -> Formatter:
        return cls._formatters[name]()

@OutputFormatterFactory.register("json")
class JsonFormatter(Formatter):
    ...

# Simple: Just use a dictionary
FORMATTERS = {
    "json": JsonFormatter,
    "csv": CsvFormatter,
    "xml": XmlFormatter,
}

# Simple beats clever
# Instead of a factory/registry pattern:
def get_formatter(name: str) -> Formatter:
    """Get formatter by name."""
    if name not in FORMATTERS:
        raise ValueError(f"Unknown format: {name}")
    return FORMATTERS[name]()
```

The factory pattern adds code without adding value here. Save patterns for when they solve real problems.

### Pattern 2: Single Responsibility Principle

Each class or function should have one reason to change.
Separate concerns into focused components.

```python
# BAD: Handler does everything
class UserHandler:
    async def create_user(self, request: Request) -> Response:
        # HTTP parsing
        data = await request.json()

        # Validation
        if not data.get("email"):
            return Response({"error": "email required"}, status=400)

        # Database access
        user = await db.execute(
            "INSERT INTO users (email, name) VALUES ($1, $2) RETURNING *",
            data["email"], data["name"]
        )

        # Response formatting
        return Response({"id": user.id, "email": user.email}, status=201)

# GOOD: Separated concerns
class UserService:
    """Business logic only."""

    def __init__(self, repo: UserRepository) -> None:
        self._repo = repo

    async def create_user(self, data: CreateUserInput) -> User:
        # Only business rules here
        user = User(email=data.email, name=data.name)
        return await self._repo.save(user)

class UserHandler:
    """HTTP concerns only."""

    def __init__(self, service: UserService) -> None:
        self._service = service

    async def create_user(self, request: Request) -> Response:
        data = CreateUserInput(**(await request.json()))
        user = await self._service.create_user(data)
        return Response(user.to_dict(), status=201)
```

Now HTTP changes don't affect business logic, and vice versa.

### Pattern 3: Separation of Concerns

Organize code into distinct layers with clear responsibilities.

```
┌─────────────────────────────────────────────────────┐
│  API Layer (handlers)                                │
│  - Parse requests                                    │
│  - Call services                                     │
│  - Format responses                                  │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│  Service Layer (business logic)                      │
│  - Domain rules and validation                       │
│  - Orchestrate operations                            │
│  - Pure functions where possible                     │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│  Repository Layer (data access)                      │
│  - SQL queries                                       │
│  - External API calls                                │
│  - Cache operations                                  │
└─────────────────────────────────────────────────────┘
```

Each layer depends only on layers below it:

```python
# Repository: Data access
class UserRepository:
    async def get_by_id(self, user_id: str) -> User | None:
        row = await self._db.fetchrow(
            "SELECT * FROM users WHERE id = $1", user_id
        )
        return User(**row) if row else None

# Service: Business logic
class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self._repo = repo

    async def get_user(self, user_id: str) -> User:
        user = await self._repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        return user

# Handler: HTTP concerns
@app.get("/users/{user_id}")
async def get_user(user_id: str) -> UserResponse:
    user = await user_service.get_user(user_id)
    return UserResponse.from_user(user)
```

### Pattern 4: Composition Over Inheritance

Build behavior by combining objects rather than inheriting.

```python
# Inheritance: Rigid and hard to test
class EmailNotificationService(NotificationService):
    def __init__(self):
        super().__init__()
        self._smtp = SmtpClient()  # Hard to mock

    def notify(self, user: User, message: str) -> None:
        self._smtp.send(user.email, message)

# Composition: Flexible and testable
class NotificationService:
    """Send notifications via multiple channels."""

    def __init__(
        self,
        email_sender: EmailSender,
        sms_sender: SmsSender | None = None,
        push_sender: PushSender | None = None,
    ) -> None:
        self._email = email_sender
        self._sms = sms_sender
        self._push = push_sender

    async def notify(
        self,
        user: User,
        message: str,
        channels: set[str] | None = None,
    ) -> None:
        channels = channels or {"email"}

        if "email" in channels:
            await self._email.send(user.email, message)

        if "sms" in channels and self._sms and user.phone:
            await self._sms.send(user.phone, message)

        if "push" in channels and self._push and user.device_token:
            await self._push.send(user.device_token, message)

# Easy to test with fakes
service = NotificationService(
    email_sender=FakeEmailSender(),
    sms_sender=FakeSmsSender(),
)
```

### Pattern 5: Rule of Three

Wait until you have three instances before abstracting.
Duplication is often better than premature abstraction.


```python
# Two similar functions? Don't abstract yet
def process_orders(orders: Sequence[Order]) -> Sequence[Result]:
    results = []
    for order in orders:
        validated = validate_order(order)
        result = process_validated_order(validated)
        results.append(result)
    return results

def process_returns(returns: Sequence[Return]) -> Sequence[Result]:
    results = []
    for ret in returns:
        validated = validate_return(ret)
        result = process_validated_return(validated)
        results.append(result)
    return results

# These look similar, but wait! Are they actually the same?
# Different validation, different processing, different errors...
# Duplication is often better than the wrong abstraction

# Only after a third case, consider if there's a real pattern
# But even then, sometimes explicit is better than abstract
```

### Pattern 6: Function Size Guidelines

Keep functions focused. Extract when a function:

- Exceeds 20-50 lines (varies by complexity)
- Serves multiple distinct purposes
- Has deeply nested logic (3+ levels)

```python
# Too long, multiple concerns mixed
def process_order(order: Order) -> Result:
    # 50 lines of validation...
    # 30 lines of inventory check...
    # 40 lines of payment processing...
    # 20 lines of notification...
    pass

# Better: Composed from focused functions
def process_order(order: Order) -> Result:
    """Process a customer order through the complete workflow."""
    validate_order(order)
    reserve_inventory(order)
    payment_result = charge_payment(order)
    send_confirmation(order, payment_result)
    return Result(success=True, order_id=order.id)
```

### Pattern 7: Dependency Injection

Pass dependencies through constructors for testability.

```python
from typing import Protocol

class Logger(Protocol):
    def info(self, msg: str, **kwargs) -> None: ...
    def error(self, msg: str, **kwargs) -> None: ...

class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int) -> None: ...

class UserService:
    """Service with injected dependencies."""

    def __init__(
        self,
        repository: UserRepository,
        cache: Cache,
        logger: Logger,
    ) -> None:
        self._repo = repository
        self._cache = cache
        self._logger = logger

    async def get_user(self, user_id: str) -> User:
        # Check cache first
        cached = await self._cache.get(f"user:{user_id}")
        if cached:
            self._logger.info("Cache hit", user_id=user_id)
            return User.from_json(cached)

        # Fetch from database
        user = await self._repo.get_by_id(user_id)
        if user:
            await self._cache.set(f"user:{user_id}", user.to_json(), ttl=300)

        return user

# Production
service = UserService(
    repository=PostgresUserRepository(db),
    cache=RedisCache(redis),
    logger=StructlogLogger(),
)

# Testing
service = UserService(
    repository=InMemoryUserRepository(),
    cache=FakeCache(),
    logger=NullLogger(),
)
```

### Pattern 8: Avoiding Common Anti-Patterns

**Don't expose internal types in APIs:**

```python
# BAD: Leaking ORM model to API
@app.get("/users/{id}")
def get_user(id: str) -> UserModel:  # SQLAlchemy model
    return db.query(UserModel).get(id)

# GOOD: Use response schemas
@app.get("/users/{id}")
def get_user(id: str) -> UserResponse:
    user = db.query(UserModel).get(id)
    return UserResponse.from_orm(user)
```

**Don't mix I/O with business logic:**

```python
# BAD: SQL embedded in business logic
def calculate_discount(user_id: str) -> float:
    user = db.query("SELECT * FROM users WHERE id = ?", user_id)
    orders = db.query("SELECT * FROM orders WHERE user_id = ?", user_id)
    # Business logic mixed with data access

# GOOD: Repository pattern
def calculate_discount(user: User, order_history: list[Order]) -> float:
    # Pure business logic, easily testable
    if len(order_history) > 10:
        return 0.15
    return 0.0
```

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
2. **Always await coroutines** to execute them
3. **Limit concurrency with semaphores** - unbounded tasks can exhaust resources
4. **Implement proper error handling** with try/except
5. **Use timeouts** to prevent hanging operations
6. **Pool connections** for better performance
7. **Never block the event loop** - use `run_in_thread` for sync code

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


# Track which loops have been wrapped (prevent double-wrapping)
_wrapped_loops: weakref.WeakSet[asyncio.AbstractEventLoop] = weakref.WeakSet()

# Cleanup callbacks per loop: dict[loop_id, list[async_callable]]
_cleanup_callbacks: dict[int, list[Callable[[], Coroutine[Any, Any, None]]]] = {}

# Thread-safe lock for modifying shared state
_lock = RLock()


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
    with _lock:
        if loop in _wrapped_loops:
            return False

        original_close = loop.close

        def _patched_close() -> None:
            loop_id = id(loop)
            callbacks = _cleanup_callbacks.pop(loop_id, [])

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
        _wrapped_loops.add(loop)

        # GC fallback: if the loop is garbage-collected without close()
        weakref.finalize(loop, lambda lid: _cleanup_callbacks.pop(lid, None), id(loop))

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
    with _lock:
        if wrap_if_needed:
            wrap_loop_close(loop)
        elif loop not in _wrapped_loops:
            raise RuntimeError("Loop is not wrapped. Call wrap_loop_close() first.")

        loop_id = id(loop)
        if loop_id not in _cleanup_callbacks:
            _cleanup_callbacks[loop_id] = []
        _cleanup_callbacks[loop_id].append(callback)
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
                return self._thread_pool.submit(loop.run_until_complete, coro)
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

| Situation | Use run_in_thread? |
|-----------|-------------------|
| Polars `.collect()`, `.sink_parquet()` | Yes — blocks on C extensions |
| DeltaTable construction, `.version()` | Yes — blocks on Rust FFI |
| `open()` / file I/O | Yes — blocks on disk I/O |
| `polars.testing.assert_frame_equal` | Yes — blocks on comparison |
| Pure Python computation (< 1ms) | No — overhead not worth it |
| `await client.get_object(...)` | No — already async |

#### InterpreterPoolExecutor (Python 3.14+)

Python 3.14 introduced `concurrent.futures.InterpreterPoolExecutor` via PEP 734.
Subinterpreters provide true parallelism (each has its own GIL) with lower
overhead than `ProcessPoolExecutor`. Use it for **CPU-bound** work that doesn't
need to share mutable state.

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

| Situation | Use |
|-----------|-----|
| CPU-bound pure Python (parsing, math) | `InterpreterPoolExecutor` — true parallelism |
| CPU-bound C extension (Polars, DeltaTable) | `run_in_thread` — C extensions already release the GIL |
| Blocking I/O (file, network) | `run_in_thread` — simpler, lower overhead |
| Needs shared mutable state | `run_in_thread` — interpreters are isolated |

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
            tg.create_task(
                _process_item_do(parallel_semaphore, item, db)
            )


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
            tasks.append(
                tg.create_task(
                    _validate_item_do(parallel_semaphore, item, db)
                )
            )

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

##### Why the nested isinstance check?

`ExceptionGroup` can be nested — a TaskGroup might contain sub-TaskGroups, each
of which can produce its own ExceptionGroups. The nested check flattens them:

```
ExceptionGroup (outer TaskGroup)
├── ValueError("bad input")           → logged directly
├── ExceptionGroup (inner TaskGroup)  → flattened
│   ├── ConnectionError("timeout")    → logged as sub-exception
│   └── IOError("disk full")          → logged as sub-exception
└── KeyError("missing field")         → logged directly
```

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
                    tg.create_task(
                        _rollback_entity_do(parallel_semaphore, entity_name, info)
                    )
        raise


async def _rollback_entity_do(
    parallel_semaphore: asyncio.Semaphore,
    entity_name: str,
    info: dict[str, Any],
) -> None:
    """Rollback a single entity to its previous version."""
    async with parallel_semaphore:
        try:
            dt = DeltaTable(info["table_uri"], storage_options=info["storage_options"])
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
    queues: dict[str, asyncio.Queue[item_dtype]] = defaultdict(
        lambda: asyncio.Queue()
    )

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

| Context | Value | Rationale |
|---------|-------|-----------|
| Database batch operations | 50 | Throughput limits |
| File processing / logging | 25 | Moderate parallelism |
| API key validation | 10 | Balance speed vs. throttling |
| Test resource creation | 20 | Fast but safe for LocalStack |
| General external API calls | 10 | Conservative default |

## Python Configuration Management

Externalize configuration from code using environment variables and typed settings. Well-managed configuration enables the same code to run in any environment without modification.

### When to Use

- Setting up a new project's configuration system
- Migrating from hardcoded values to environment variables
- Implementing pydantic-settings for typed configuration
- Managing secrets and sensitive values
- Creating environment-specific settings (dev/staging/prod)
- Validating configuration at application startup

### Core Concepts

1. **Externalized Configuration**: All environment-specific values (URLs, secrets, feature flags) come from environment variables, not code.
2. **Typed Settings**: Parse and validate the configuration into typed objects at startup, rather than scattering it throughout the code.
3. **Fail Fast**: Validate all required configuration at application boot. Missing config should crash immediately with a clear message.
4. **Sensible Defaults**: Provide reasonable defaults for local development while requiring explicit values for sensitive settings.

```python
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    database_url: str = Field(alias="DATABASE_URL")
    api_key: str = Field(alias="API_KEY")
    debug: bool = Field(default=False, alias="DEBUG")

settings = Settings()  # Loads from environment
```

### Best Practices Summary

1. **Never hardcode config** - All environment-specific values from env vars
2. **Use typed settings** - Pydantic-settings with validation
3. **Fail fast** - Crash on missing required config at startup
4. **Provide dev defaults** - Make local development easy
5. **Never commit secrets** - Use `.env` files (gitignored) or secret managers
6. **Namespace variables** - `DB_HOST`, `REDIS_URL` for clarity
7. **Import settings singleton** - Don't call `os.getenv()` throughout code
8. **Document all variables** - README should list required env vars
9. **Validate early** - Check config correctness at boot time
10. **Use secrets_dir** - Support mounted secrets in containers

### Fundamental Patterns

#### Pattern 1: Typed Settings with Pydantic

Create a central settings class that loads and validates all configurations.

```python
from pydantic_settings import BaseSettings
from pydantic import Field, PostgresDsn, ValidationError
import sys

class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # Database
    db_host: str = Field(alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(alias="DB_NAME")
    db_user: str = Field(alias="DB_USER")
    db_password: str = Field(alias="DB_PASSWORD")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")

    # API Keys
    api_secret_key: str = Field(alias="API_SECRET_KEY")

    # Feature flags
    enable_new_feature: bool = Field(default=False, alias="ENABLE_NEW_FEATURE")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

# Create singleton instance at module load (__init__.py)
SETTINGS = Settings()
```

Import `SETTINGS` throughout your application:

```python
from app import SETTINGS

def get_database_connection():
    return connect(
        host=SETTINGS.db_host,
        port=SETTINGS.db_port,
        database=SETTINGS.db_name,
    )
```

#### Pattern 2: Fail Fast on Missing Configuration

Required settings should crash the application immediately with a clear error.

```python
from pydantic_settings import BaseSettings
from pydantic import Field, ValidationError
import sys

class Settings(BaseSettings):
    # Required - no default means it must be set
    api_key: str = Field(alias="API_KEY")
    database_url: str = Field(alias="DATABASE_URL")

    # Optional with defaults
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

try:
    settings = Settings()
except ValidationError as e:
    for error in e.errors():
        field = error["loc"][0]
        print(f”Setting {field}: {error['msg']}")
```

A clear error at startup is better than a cryptic `None` failure mid-request.

#### Pattern 3: Local Development Defaults

Provide sensible defaults for local development while requiring explicit values for secrets.

```python
class Settings(BaseSettings):
    # Has local default, but prod will override
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")

    # Always required - no default for secrets
    db_password: str = Field(alias="DB_PASSWORD")
    api_secret_key: str = Field(alias="API_SECRET_KEY")

    # Development convenience
    debug: bool = Field(default=False, alias="DEBUG")

    model_config = {"env_file": ".env"}
```

Create a `.env` file for local development (never commit this):

```bash
# .env (add to .gitignore)
DB_PASSWORD=local_dev_password
API_SECRET_KEY=dev-secret-key
DEBUG=true
```

#### Pattern 4: Namespaced Environment Variables

Prefix related variables for clarity and easy debugging.

```bash
# Database configuration
DB_HOST=localhost
DB_PORT=5432
DB_NAME=myapp
DB_USER=admin
DB_PASSWORD=secret

# Redis configuration
REDIS_URL=redis://localhost:6379
REDIS_MAX_CONNECTIONS=10

# Authentication
AUTH_SECRET_KEY=your-secret-key
AUTH_TOKEN_EXPIRY_SECONDS=3600
AUTH_ALGORITHM=HS256

# Feature flags
FEATURE_NEW_CHECKOUT=true
FEATURE_BETA_UI=false
```

Makes `env | grep DB_` useful for debugging.

### Pattern 5: Type Coercion

Pydantic handles common conversions automatically.

```python
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator

class Settings(BaseSettings):
    # Automatically converts "true", "1", "yes" to True
    debug: bool = False

    # Automatically converts string to int
    max_connections: int = 100

    # Parse comma-separated string to list
    allowed_hosts: list[str] = Field(default_factory=list)

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [host.strip() for host in v.split(",") if host.strip()]
        return v
```

Usage:

```bash
ALLOWED_HOSTS=example.com,api.example.com,localhost
MAX_CONNECTIONS=50
DEBUG=true
```

### Pattern 6: Environment-Specific Configuration

Use an environment enum to switch behavior.

```python
from enum import Enum
from pydantic_settings import BaseSettings
from pydantic import Field, computed_field

class Environment(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"

class Settings(BaseSettings):
    environment: Environment = Field(
        default=Environment.LOCAL,
        alias="ENVIRONMENT",
    )

    # Settings that vary by environment
    log_level: str = Field(default="DEBUG", alias="LOG_LEVEL")

    @computed_field
    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @computed_field
    @property
    def is_local(self) -> bool:
        return self.environment == Environment.LOCAL

# Usage
if settings.is_production:
    configure_production_logging()
else:
    configure_debug_logging()
```

### Pattern 7: Nested Configuration Groups

Organize related settings into nested models.

```python
from pydantic import BaseModel
from pydantic_settings import BaseSettings

class DatabaseSettings(BaseModel):
    host: str = "localhost"
    port: int = 5432
    name: str
    user: str
    password: str

class RedisSettings(BaseModel):
    url: str = "redis://localhost:6379"
    max_connections: int = 10

class Settings(BaseSettings):
    database: DatabaseSettings
    redis: RedisSettings
    debug: bool = False

    model_config = {
        "env_nested_delimiter": "__",
        "env_file": ".env",
    }
```

Environment variables use double underscore for nesting:

```bash
DATABASE__HOST=db.example.com
DATABASE__PORT=5432
DATABASE__NAME=myapp
DATABASE__USER=admin
DATABASE__PASSWORD=secret
REDIS__URL=redis://redis.example.com:6379
```

### Pattern 8: Secrets from Files

For container environments, read secrets from mounted files.

```python
from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path

class Settings(BaseSettings):
    # Read from environment variable or file
    db_password: str = Field(alias="DB_PASSWORD")

    model_config = {
        "secrets_dir": "/run/secrets",  # Docker secrets location
    }
```

Pydantic will look for `/run/secrets/db_password` if the env var isn't set.

### Pattern 9: Configuration Validation

Add custom validation for complex requirements.

```python
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator

class Settings(BaseSettings):
    db_host: str = Field(alias="DB_HOST")
    db_port: int = Field(alias="DB_PORT")
    read_replica_host: str | None = Field(default=None, alias="READ_REPLICA_HOST")
    read_replica_port: int = Field(default=5432, alias="READ_REPLICA_PORT")

    @model_validator(mode="after")
    def validate_replica_settings(self):
        if self.read_replica_host and self.read_replica_port == self.db_port:
            if self.read_replica_host == self.db_host:
                raise ValueError(
                    "Read replica cannot be the same as primary database"
                )
        return self
```

## Testing Patterns

Detailed testing conventions for async-first Python projects using pytest.

### When to Use

- Writing unit tests for Python code
- Creating integration tests
- Mocking external dependencies and services
- Testing async code and concurrent operations
- Debugging failing tests

### Best Practices Summary

1. **Write tests first** (TDD) or alongside code
2. **One assertion per test** when possible
3. **Use descriptive test names** that explain behavior
4. **Keep tests independent** and isolated
5. **Use fixtures** for setup and teardown
6. **Mock external dependencies** appropriately
7. **Parametrize tests** to reduce duplication
8. **Test edge cases** and error conditions
9. **Measure coverage** but focus on quality

### Test Types

- **Unit Tests**: Test individual functions/classes in isolation
- **Integration Tests**: Test interaction between components
- **End-to-end (or Functional) Tests**: Test complete features end-to-end
- **Data Tests**: Test complete data workflows
- **Performance Tests**: Measure speed and resource usage

### Test Infrastructure

#### Tech Stack

- **Framework**: pytest with pytest-asyncio (auto mode)
- **Parallelism**: pytest-xdist with workers (`-n auto --dist worksteal`)
- **AWS Mocking**: LocalStack (Docker container, managed by custom pytest plugin)
- **Event Loop**: uvloop (session-scoped fixture)
- **Leak Detection**: pyleak for task and thread leak detection
- **Timeouts**: 5s per test, 30s per slow test, 60s per data/localstack test, 300s per session

#### pytest Plugins and Dependencies

- pyleak: identify async or thread leaks
- pytest-asyncio: async tests
- pytest-cov: coverage
- pytest-dotenv: load environment variables
- pytest-rerunfailures: rerun failed
- pytest-timeout: timeout test
- pytest-unordered: random test order
- pytest-xdist: parallel execution
- python-on-whales: control Docker
- freezegun: freezes the datetime
- coverage: coverage
- filelock: lock based on file (to lock between xdist processes)
- localstack-client: mock boto3 to use Localstack
- hypothesis: random value generator for tests

#### pytest.ini Configuration

```ini
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = session
pythonpath = ["."]
env_override_existing_values = 1
env_files = tests/pytest.env
testpaths = tests
addopts = -n auto --capture=tee-sys --color=yes --dist worksteal
timeout = 5
session_timeout = 300

markers =
    data: marks data tests
    integration: marks integration tests
    unit: marks unit tests
    e2e: marks end-to-end tests
    slow: marks tests as slow
    localstack: tests that expect Localstack environment (S3, DynamoDB, SQS, SNS, etc.)
```

### Test Organization

#### File Layout

- Unit tests live in `tests/unit/`
- Data tests live in `tests/data/`
- Integration tests live in `tests/integration/`
- End-to-end tests live in `tests/e2e/`
- Test configurations live in `tests/configuration/`
- Custom pytest plugins live in `tests/plugins/`
- Shared fixtures and helpers in `tests/conftest.py`

#### Test Naming

- Files: `test_{module_name}.py` for unit tests, `test_{scenario}.py` for data/integration/e2e tests
- Tests: `test_<unit>_<scenario>_<expected_outcome>` (expected_outcome is optional)

```python
# Pattern: test_<unit>_<scenario>_<expected>
def test_create_user_with_valid_data_returns_user():
    ...

def test_create_user_with_duplicate_email_raises_conflict():
    ...

def test_get_user_with_unknown_id_returns_none():
    ...

# Good test names - clear and descriptive
def test_user_creation_with_valid_data():
    """Clear name describes what is being tested."""
    pass

def test_login_fails_with_invalid_password():
    """Name describes expected behavior."""
    pass

def test_api_returns_404_for_missing_resource():
    """Specific about inputs and expected outcomes."""
    pass
```

### Pytest Markers

```python
@pytest.mark.localstack# Tests requiring LocalStack (S3, DynamoDB, SQS, SNS, etc.)
@pytest.mark.data # Full data pipeline tests (probably uses LocalStack)
@pytest.mark.slow # Slow-running tests
@pytest.mark.timeout(5) # Override per-test timeout
@pytest.mark.no_leaks_local(threads=False) # Leak detection (exclude thread checks)

# NEVER use @pytest.mark.asyncio — conftest must auto-adds it via pytest_collection_modifyitems
```
#### Automatic Asyncio Marker Injection

Add this hook in conftest.py so you never need `@pytest.mark.asyncio` on tests:

```python
import pytest
import pytest_asyncio


def pytest_collection_modifyitems(
    session: pytest.Session,
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Auto-add asyncio markers to async tests.

    This removes the need to manually decorate every async test with
    @pytest.mark.asyncio. Session-scoped for standalone async functions,
    class-scoped for TestCase methods.
    """
    session_scope_marker = pytest.mark.asyncio(loop_scope="session")

    for item in items:
        if pytest_asyncio.is_async_test(item):
            # Standalone async test → session scope
            item.add_marker(session_scope_marker, append=False)
```

### Required Class Tests

Every class must have tests for these structural properties. This prevents accidental breaking changes (removing an attribute, making a method sync, etc.):

```python
import inspect
from something import Client

class BaseClient:
    name: str

class Client(BaseClient):
    last_name: str

    async def get_full_name(self):
        return self.name + self.last_name

client = Client()

async def test_client_instance_creation() -> None:
    """Verify instance is of the expected class."""
    assert isinstance(client, Client)

async def test_client_inherits_base() -> None:
    """Verify inheritance from base_client."""
    assert issubclass(Client, BaseClient)

async def test_client_has_attributes() -> None:
    “""Verify all declared attributes exist."""
    attributes = ["get_full_name"]
    for attribute_name in attributes:
        assert hasattr(client, attribute_name)

async def test_client_methods_are_async() -> None:
    """Verify public methods are async."""
    methods = ["get_full_name"]
    for method_name in methods:
        method = getattr(client, method_name)
        assert inspect.iscoroutinefunction(method)
```

### Mocking Patterns

#### MonkeyPatch as Context Manager

Always use `MonkeyPatch.context()` as a context manager — this ensures patches are reverted even if the test fails:

```python
async def test_get_url_success() -> None:
    """Test successful URL retrieval."""
    with MonkeyPatch.context() as monkeypatch:
        mock = AsyncMock(return_value={"QueueUrl": "http://example/q1"})
        monkeypatch.setattr(
            client._client,
            "get_queue_url",
            mock,
        )
        url = await client.get_url("q1")
        assert url.endswith("/q1")

    #check if the mock was called once with a specific parameter
    mock.assert_called_once_with("q1")
```

#### AsyncMock (stdlib)

Python 3.8+ includes `AsyncMock` in the standard library (`unittest.mock`). It
natively supports `await`, `assert_awaited_*` methods, and async context managers.
No custom mock class is needed.

```python
from unittest.mock import AsyncMock
```

Usage patterns:

```python
# Single return value
monkeypatch.setattr(
    client._client, "generate_url",
    AsyncMock(return_value="http://download/url"),
)

# Multiple return values (pagination simulation)
monkeypatch.setattr(
    client._client, "list_objects_v2",
    AsyncMock(side_effect=[
        {"Contents": [{"Key": "file1.csv"}], "IsTruncated": True},
        {"Contents": [{"Key": "file2.csv"}], "IsTruncated": False},
    ]),
)

# Exception simulation
monkeypatch.setattr(
    client._client, "get_item",
    AsyncMock(side_effect=ClientError({"Error": {"Code": "404"}}, "get")),
)
```

#### Module-Level MonkeyPatching

For global mocks that apply across all tests (e.g., replacing config loading with local file reads):

```python
# In conftest.py — module-level patching

MONKEYPATCH = pytest.MonkeyPatch()

async def _mock_get_configuration(cls, config_name: str) -> Any:
    """Replace remote config loading with local JSON files."""
    file = f"{os.path.dirname(__file__)}/configuration/{config_name}.json"
    async with aiofiles.open(file) as fp:
        content = await fp.read()
    return orjson.loads(content)

MONKEYPATCH.setattr(
    “some_class.get_configuration",
    _mock_get_configuration,
)
```


### Data Tests

Data tests verify the full pipeline end-to-end (probably using LocalStack).

```python
@pytest.mark.data
async def test_step_1_load_first_file() -> None:
    """Load initial source file and verify target output."""

    pipeline = await create_pipeline()

    # 1. Create parquet file
    await create_parquet(
        filename="file1.parquet",
        data=[{"id": 1, "name": "order-001", "amount": 100}]
    )

    # 2. Run pipeline for the parquet
    await pipeline(filename="file1.parquet")

    # 3. Verify target data
    lf = await get_orders()

    expected_lf = pl.LazyFrame(...)
    assert lf == lf_expected

    # 4. Verify no duplicates
    orders = await get_order_by_id(1)

    assert len(orders) == 1
```

### Unit Tests

Unit tests mock external services and test individual methods:

```python
async def test_get_files_pagination_and_filters() -> None:
    """Test file listing with pagination and suffix filtering."""

    storage = await storage_client().load()

    with MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            storage._client, "list_objects_v2",
            AsyncMock(side_effect=[
                {
                    "Contents": [
                        {"Key": "prefix/file1.csv"},
                        {"Key": "prefix/file2.parquet"},
                    ],
                    "IsTruncated": True,
                    "NextContinuationToken": "tok",
                },
                {
                    "Contents": [{"Key": "prefix/file3.parquet"}],
                    "IsTruncated": False,
                },
            ]),
        )
        res = await storage.get_files(
            bucket="my-bucket", prefix="prefix/", suffix=".parquet",
        )
        keys = [file["Key"] for file in res]

        assert "prefix/file2.parquet” in keys
        assert "prefix/file3.parquet” in keys
        assert "prefix/file1.csv” not in keys
```

### LocalStack Resource Setup

1. Resource names must be unique across tests to avoid collisions with pytest-xdist workers.
2. Create test-specific resources inside the test.
3. Create SHARED resources in parallel during test session setup using `asyncio.TaskGroup`:

```python
async def setup_localstack_resources() -> None:
    """Create all AWS resources needed for tests.

    Uses TaskGroup with a semaphore to create resources in parallel
    while respecting LocalStack's concurrency limits.
    """
    semaphore = asyncio.Semaphore(20)

    topics = [{"topic_name": "pytest-notifications"}]
    queues = [
        {"queue_name": "pytest-source-queue", "fifo": False},
        {"queue_name": "pytest-processing.fifo", "fifo": True},
    ]
    tables = [
        {
            "table_name": "pytest-file-log",
            "key_schema": [
                {"AttributeName": "id", "KeyType": "HASH"},
            ],
            "attribute_definitions": [
                {"AttributeName": "id", "AttributeType": "S"},
            ],
        },
    ]
    buckets = [{"bucket_name": f"bp-pytest-source-{i}"} for i in range(1, 5)]

    async with asyncio.TaskGroup() as tg:
        for topic in topics:
            tg.create_task(create_topic(semaphore, **topic))
        for queue in queues:
            tg.create_task(create_queue(semaphore, **queue))
        for table in tables:
            tg.create_task(create_table(semaphore, **table))
        for bucket in buckets:
            tg.create_task(create_bucket(semaphore, **bucket))
```

### Custom Pytest Plugins

#### Debugger-Aware Worker Disabling

Disable pytest-xdist when running a small number of tests or debugging:

```python
# tests/plugins/pytest_bootstrap.py

import os
import sys

THRESHOLD = 5
DEBUG_THRESHOLD = 3

def _debugger_active() -> bool:
    """Check if a debugger is currently active."""
    return (
        "debugpy" in sys.modules
        or bool(os.environ.get("VSCODE_PID"))
        or bool(os.environ.get("PYTHONBREAKPOINT"))
    )

def _heuristic_test_count_from_args(args: list[str]) -> int | None:
    """Estimate test count from pytest CLI arguments."""
    targets = [a for a in args if a and not a.startswith("-")]
    nodeids = [t for t in targets if "::" in t]
    return len(nodeids) if nodeids else None

def _disable_xdist(early_config: Any, args: list[str]) -> None:
    """Disable pytest-xdist by setting -n0."""
    for i, arg in enumerate(args):
        if arg == "-n" or arg.startswith("-n"):
            if arg == "-n" and i + 1 < len(args):
                args[i + 1] = "0"
            else:
                args[i] = "-n0"
            return
    args.extend(["-n", "0"])

def pytest_load_initial_conftests(
    early_config: Any, parser: Any, args: list[str],
) -> None:
    """Disable xdist for small test sets or when debugging."""
    est = _heuristic_test_count_from_args(args)

    if _debugger_active() and est is not None and est < DEBUG_THRESHOLD:
        _disable_xdist(early_config, args)
        return

    if est is not None and est < THRESHOLD:
        _disable_xdist(early_config, args)
```

### Fundamental Patterns

#### Pattern 1: Basic pytest Tests

```python
# test_calculator.py
import pytest

def test_addition():
    """Test addition."""
    calc = Calculator()
    assert calc.add(2, 3) == 5
    assert calc.add(-1, 1) == 0
    assert calc.add(0, 0) == 0

def test_subtraction():
    """Test subtraction."""
    calc = Calculator()
    assert calc.subtract(5, 3) == 2
    assert calc.subtract(0, 5) == -5

def test_multiplication():
    """Test multiplication."""
    calc = Calculator()
    assert calc.multiply(3, 4) == 12
    assert calc.multiply(0, 5) == 0

def test_division():
    """Test division."""
    calc = Calculator()
    assert calc.divide(6, 3) == 2
    assert calc.divide(5, 2) == 2.5

def test_division_by_zero():
    """Test division by zero raises error."""
    calc = Calculator()
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        calc.divide(5, 0)
```

#### Pattern 2: Fixtures for Setup and Teardown

**conftest.py**

```python
import pytest
from typing import Generator

class Database:
    """Simple database class."""

    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.connected = False

    def connect(self):
        """Connect to database."""
        self.connected = True

    def disconnect(self):
        """Disconnect from database."""
        self.connected = False

    def query(self, sql: str) -> list:
        """Execute query."""
        if not self.connected:
            raise RuntimeError("Not connected")
        return [{"id": 1, "name": "Test"}]

@pytest.fixture
def db() -> Generator[Database, None, None]:
    """Fixture that provides connected database."""
    # Setup
    database = Database("sqlite:///:memory:")
    database.connect()

    # Provide to test
    yield database

    # Teardown
    database.disconnect()

@pytest.fixture(scope=“session”, params=[{
    "database_url": "postgresql://localhost/test",
    "api_key": "test-key",
    "debug": True
}])
def app_config(request):
    """Session-scoped fixture - created once per test session."""
    return request.param

@pytest.fixture(scope="module")
def api_client(app_config):
    """Module-scoped fixture - created once per test module."""
    # Setup expensive resource
    client = {"config": app_config, "session": "active"}
    yield client
    # Cleanup
    client["session"] = "closed"
```

**test_database.py**

```python
import pytest
from tests.conftest import db, api_client

def test_database_query(db):
    """Test database query with fixture."""
    results = db.query("SELECT * FROM users")
    assert len(results) == 1
    assert results[0]["name"] == "Test"

def test_api_client(api_client):
    """Test using api client fixture."""
    assert api_client["session"] == "active"
    assert api_client["config"]["debug"] is True
```

#### Pattern 3: Parameterized Tests

```python
# test_validation.py
import pytest

def is_valid_email(email: str) -> bool:
    """Check if email is valid."""
    parts = email.split("@")
    return len(parts) == 2 and len(parts[0]) > 0 and "." in parts[1]

@pytest.mark.parametrize("email,expected", [
    ("user@example.com", True),
    ("test.user@domain.co.uk", True),
    ("invalid.email", False),
    ("@example.com", False),
    ("user@domain", False),
    ("", False),
])
def test_email_validation(email, expected):
    """Test email validation with various inputs."""
    assert is_valid_email(email) == expected

@pytest.mark.parametrize("a,b,expected", [
    (2, 3, 5),
    (0, 0, 0),
    (-1, 1, 0),
    (100, 200, 300),
    (-5, -5, -10),
])
def test_addition_parameterized(a, b, expected):
    """Test addition with multiple parameter sets."""
    from test_calculator import Calculator
    calc = Calculator()
    assert calc.add(a, b) == expected

# Using pytest.param for special cases
@pytest.mark.parametrize("value,expected", [
    pytest.param(1, True, id="positive"),
    pytest.param(0, False, id="zero"),
    pytest.param(-1, False, id="negative"),
])
def test_is_positive(value, expected):
    """Test with custom test IDs."""
    assert (value > 0) == expected
```

#### Pattern 4: Testing Exceptions

```python
# test_exceptions.py
import pytest

def divide(a: float, b: float) -> float:
    """Divide a by b."""
    if b == 0:
        raise ZeroDivisionError("Division by zero")
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("Arguments must be numbers")
    return a / b


def test_zero_division():
    """Test exception is raised for division by zero."""
    with pytest.raises(ZeroDivisionError):
        divide(10, 0)


def test_zero_division_with_message():
    """Test exception message."""
    with pytest.raises(ZeroDivisionError, match="Division by zero"):
        divide(5, 0)


def test_type_error():
    """Test type error exception."""
    with pytest.raises(TypeError, match="must be numbers"):
        divide("10", 5)


def test_exception_info():
    """Test accessing exception info."""
    with pytest.raises(ValueError) as exc_info:
        int("not a number")

    assert "invalid literal" in str(exc_info.value)
```

#### Pattern 5: Random Values Testing

```python
# test_properties.py
from hypothesis import given, strategies as st
import pytest

def reverse_string(s: str) -> str:
    """Reverse a string."""
    return s[::-1]

@given(st.text())
def test_reverse_twice_is_original(s):
    """Property: reversing twice returns original."""
    assert reverse_string(reverse_string(s)) == s

@given(st.text())
def test_reverse_length(s):
    """Property: reversed string has same length."""
    assert len(reverse_string(s)) == len(s)

@given(st.integers(), st.integers())
def test_addition_commutative(a, b):
    """Property: addition is commutative."""
    assert a + b == b + a

@given(st.lists(st.integers()))
def test_sorted_list_properties(lst):
    """Property: sorted list is ordered."""
    sorted_lst = sorted(lst)

    # Same length
    assert len(sorted_lst) == len(lst)

    # All elements present
    assert set(sorted_lst) == set(lst)

    # Is ordered
    for i in range(len(sorted_lst) - 1):
        assert sorted_lst[i] <= sorted_lst[i + 1]
```


#### Pattern 6: Frozen Time

Use freezegun to control time in tests for predictable time-dependent behavior.

```python
from freezegun import freeze_time
from datetime import datetime, timedelta

@freeze_time("2026-01-15 10:00:00")
def test_token_expiry():
    """Test token expires at correct time."""
    token = create_token(expires_in_seconds=3600)
    assert token.expires_at == datetime(2026, 1, 15, 11, 0, 0)

@freeze_time("2026-01-15 10:00:00")
def test_is_expired_returns_false_before_expiry():
    """Test token is not expired when within validity period."""
    token = create_token(expires_in_seconds=3600)
    assert not token.is_expired()

@freeze_time("2026-01-15 12:00:00")
def test_is_expired_returns_true_after_expiry():
    """Test token is expired after validity period."""
    token = Token(expires_at=datetime(2026, 1, 15, 11, 30, 0))
    assert token.is_expired()

def test_with_time_travel():
    """Test behavior across time using freeze_time context."""
    with freeze_time("2026-01-01") as frozen_time:
        item = create_item()
        assert item.created_at == datetime(2026, 1, 1)

        # Move forward in time
        frozen_time.move_to("2026-01-15")
        assert item.age_days == 14
```

### Test Design Principles

#### One Behavior Per Test

Each test should verify exactly one behavior. This makes failures easy to diagnose and tests easy to maintain.

```python
# BAD - testing multiple behaviors
def test_user_service():
    user = service.create_user(data)
    assert user.id is not None
    assert user.email == data["email"]
    updated = service.update_user(user.id, {"name": "New"})
    assert updated.name == "New"

# GOOD - focused tests
def test_create_user_assigns_id():
    user = service.create_user(data)
    assert user.id is not None

def test_create_user_stores_email():
    user = service.create_user(data)
    assert user.email == data["email"]

def test_update_user_changes_name():
    user = service.create_user(data)
    updated = service.update_user(user.id, {"name": "New"})
    assert updated.name == "New"
```

#### Test Error Paths

Always test failure cases, not just happy paths.

```python
def test_get_user_raises_not_found():
    with pytest.raises(UserNotFoundError) as exc_info:
        service.get_user("nonexistent-id")

    assert "nonexistent-id" in str(exc_info.value)

def test_create_user_rejects_invalid_email():
    with pytest.raises(ValueError, match="Invalid email format"):
        service.create_user({"email": "not-an-email"})
```

#### Others

- Test edge cases
- Test with null, negative, positive, UTF-8, Unicode values
- Test connection failures/intermittence in integration tests (if possible)
- Verify retry logic works correctly using mock side effects

### Running Tests

```bash
# All tests (15 parallel workers)
uv run pytest -n10

# Without data/slow/localstack tests (quick check)
uv run pytest tests -m "not slow and not data and not localstack"

# Single test (disable xdist for cleaner output)
uv run pytest tests -n0

# Validate test collection after creating new tests
uv run pytest tests --collect-only
```

## Quick Review Checklist

Before finalizing code, verify:

- [ ] All functions have type hints (parameters + return)
- [ ] All functions have Google-style docstrings
- [ ] No scattered timeout/retry logic
- [ ] No mixed I/O and business logic
- [ ] No bare `except Exception: pass` (allowed only in a few exceptional cases)
- [ ] Batch operations handle partial failures
- [ ] Collections have type parameters
- [ ] Resources use context managers or explicit cleanup
- [ ] No double retry (app + infrastructure)
- [ ] No hard-coded configuration or secrets
- [ ] No exposed internal types in APIs (ORM models, protobufs)
- [ ] No missing user input validation
- [ ] The application is thread-safe
- [ ] No blocking calls in async code
- [ ] All raises are specifics (`ValueError`, `TypeError`), not generic `Exception`
- [ ] All async functions are awaited
- [ ] Tests cover error paths and edge cases

## Pre-Commit Checklist

Before committing code, verify:

- [ ] The README is updated with all the changes
- [ ] The CHANGELOG is updated with all the changes
- [ ] All tests are green (including pyleak loop and thread leaks)
- [ ] prek (pre-commit) has no issues
