# Type hints — full reference

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

### Type Hints

#### Required Patterns

```python
# Use collections.abc for immutable parameter types
from collections.abc import Mapping, Sequence


# Parameters: immutable types to prevent accidental mutation
async def process(items: Sequence[str], config: Mapping[str, Any]) -> Mapping[str, Any]: ...


# Return types: immutable types for cached functions/methods to prevent accidental mutation in cached results
@cached
async def get_items_cached() -> Sequence[Mapping[str, str]]: ...


# Union types with pipe operator
connection: Connection | None = None
result: str | int = 0


# Literal for constrained values
async def get_path(layer: Literal["raw", "curated"]) -> str: ...


# Structured data is a Pydantic model, never a TypedDict (banned — validates nothing)
class EntityInfo(BaseModel):
    model_config = PYDANTIC_CONFIG | ConfigDict(frozen=True)

    bucket: RequiredText
    source: RequiredText
    schema_name: RequiredText
    table: RequiredText
    customer: OptionalText = None


# Overloads for polymorphic return types
@overload
async def get_items(
    self,
    bucket: str,
    include_versions: Literal[False] = False,
) -> Sequence[Item]: ...


@overload
async def get_items(
    self,
    bucket: str,
    include_versions: Literal[True] = True,
) -> Sequence[ItemVersion]: ...


async def get_items(
    self,
    bucket: str,
    include_versions: bool = False,
) -> Sequence[Item] | Sequence[ItemVersion]: ...


# TYPE_CHECKING guard — still needed for runtime type swapping
# (providing a richer static type vs. a lighter runtime type)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client
else:
    from botocore.client import BaseClient as S3Client

# NOTE: On the 3.12 baseline, annotations are evaluated eagerly at def-time
# (PEP 649 lazy annotations are 3.14-only). Add `from __future__ import annotations`
# (PEP 563) for forward references and TYPE_CHECKING-only imports — without it,
# an annotation naming a TYPE_CHECKING-only import raises NameError at runtime.
# TYPE_CHECKING is STILL needed regardless for:
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

**A Protocol implementer exposes exactly the Protocol's public surface — no extra
public members.** If a class needs a helper that isn't on the interface, make it a
private instance member (`self._x`), not a public method/attr. A public name absent
from the Protocol means either the Protocol is incomplete or the member shouldn't
be public — decide, don't leak it.

#### Strict-typing gates (enforced — don't suppress)

These fail the mypy-strict / prek gate; fix them at the seam rather than silencing:

- **`Final` on what must not change.** Annotate class-level constants `Final`; mark a
  base/protocol method that must not be overridden `Final` too. mypy flags a subclass
  that redeclares a `Final` attribute as `[misc]` — that's the signal, not noise.
- **Annotations, never type comments.** Use `x: int`, never `# type:` comment syntax.
- **No blanket suppressions.** Every `# type: ignore[code]` / `# noqa: CODE` names its
  specific code; bare `# type: ignore` / `# noqa` are blocked, and a stale suppression
  (`[unused-ignore]`) fails the gate — delete it.
- **`no-any-return`.** When a typed function would return an inferred `Any` (untyped
  lib call, `dict.get`, `json.loads`), narrow it at the boundary with `cast(...)` or an
  explicit type. Don't let `Any` escape a typed return — it's a recurring strict-mode blocker.

#### Type Aliases and Callable Types

Define reusable type aliases for complex types and callback signatures.

```python
from collections.abc import Callable, Awaitable, Sequence

# Simple type aliases — PEP 695 `type` statement (lazily evaluated, no import)
type EntityId = str
type S3Uri = str

# Complex type aliases
type AsyncHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
type ProgressCallback = Callable[[int, int], None]  # (current, total)

# Legacy: `X: TypeAlias = ...` (needs `from typing import TypeAlias`) is what
# you'll see in pre-3.12 code. Read it, don't write it.


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
    items: Sequence[Item],
    on_progress: ProgressCallback | None = None,
) -> Sequence[ProcessResult]:
    """Process items with optional progress callback."""
    for i, item in enumerate(items):
        if on_progress:
            on_progress(i, len(items))
        ...
```

#### Generic Functions and Classes

Declare type parameters with **PEP 695 inline syntax** — `def first[T](...)`,
`class Stack[T]:`, `type EntityId = str`. The type parameter is scoped to the thing
that declares it, so there's no module-level variable to name, import, or keep in
sync. No `TypeVar`, no `ParamSpec`, no `Generic[...]` base.

```python
from collections.abc import Callable, Coroutine, Sequence


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


# Constraints and bounds, inline
def serialize[T: (str, bytes)](value: T) -> T:
    """Serialize a value constrained to str or bytes."""
    ...


def largest[T: float](items: Sequence[T]) -> T:
    """Return the largest item (upper bound: any float-comparable)."""
    return max(items)


# ParamSpec, inline — `**P` forwards a wrapped callable's whole signature
async def run[**P, T](
    fn: Callable[P, Coroutine[Any, Any, T]],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """Await fn with its arguments forwarded unchanged."""
    return await fn(*args, **kwargs)
```

**Legacy form — read it, don't write it.** Explicit `TypeVar` / `ParamSpec` +
`Generic[...]` is what pre-3.12 code (and any project still on a <3.12 floor) must
use. Same semantics, more boilerplate, and the type variable leaks into module scope:

```python
from typing import Generic, TypeVar

T = TypeVar("T")


def first(items: Sequence[T]) -> T:  # legacy equivalent of `def first[T]`
    """Return the first item from a sequence."""
    return items[0]


class Stack(Generic[T]):  # legacy equivalent of `class Stack[T]`
    """A generic stack."""
```

#### Naming for Types

- Model names: `PascalCase` (e.g., `EntityInfo`, `OrderRow`). `TypedDict` is banned, see [data-modeling.md](data-modeling.md)
- Protocol names: `snake_case` matching the class convention (e.g., `loadable_client`, `cacheable`)
- Type aliases (PEP 695 `type` statement): `PascalCase` (e.g., `type EntityId = str`, `type AsyncHandler = ...`)
- Type variables: declared inline, PEP 695 — `def func[T]()`, `class Foo[T]:`, `async def run[**P, T]()`
- Type variables (legacy, in pre-3.12 code you read): `T = TypeVar("T")`, `P = ParamSpec("P")`

#### Constrained id aliases — zero is not an identifier

Every numeric `*_id` uses **one shared alias**. Never use a bare `int`, and never repeat
`Field(gt=0)` at each site:

```python
# myapp/core/type_utils.py — the one owner
type PositiveId = Annotated[int, Field(gt=0)]
type OptionalPositiveId = PositiveId | None  # absence is spelled ONLY as None


class TicketRow(BaseModel):
    model_config = PYDANTIC_CONFIG

    org_id: PositiveId
    parent_id: OptionalPositiveId = None
    linked_ids: list[PositiveId]  # collections take the element type
```

`SERIAL`/`IDENTITY` columns start at 1, so a `0` or a negative id can only come from an `or 0`
fallback, an unset default, or a column the query forgot to project. That is the org-0 incident
([error-handling.md](error-handling.md#no-identity-or-falsy-literal-fallbacks)). `gt` is a
constraint, not a coercion, so it also holds under a lax request config: a request DTO answers
`0` with a 422. **Never widen it back.** A required id that defaults to `0` is the same bug in
Pydantic clothing. If `0` is a live "none" sentinel somewhere, that is a naming bug. Track it as
the single named exception and model the sentinel as `None`.
