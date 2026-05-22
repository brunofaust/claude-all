# Type hints — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

### Type Hints

#### Required Patterns

```python
# Use collections.abc for immutable parameter types
from collections.abc import Mapping, Sequence


# Parameters: immutable types to prevent accidental mutation
async def process(
    items: Sequence[str], config: Mapping[str, Any]
) -> Mapping[str, Any]: ...


# Return types: immutable types for cached functions/methods to prevent accidental mutation in cached results
@cached
async def get_items_cached() -> Sequence[Mapping[str, str]]: ...


# Union types with pipe operator
connection: Connection | None = None
result: str | int = 0


# Literal for constrained values
async def get_path(layer: Literal["raw", "curated"]) -> str: ...


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
    self,
    bucket: str,
    include_versions: Literal[False] = False,
) -> Sequence[item_dtype]: ...


@overload
async def get_items(
    self,
    bucket: str,
    include_versions: Literal[True] = True,
) -> Sequence[item_version_dtype]: ...


async def get_items(
    self,
    bucket: str,
    include_versions: bool = False,
) -> Sequence[item_dtype] | Sequence[item_version_dtype]: ...


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
