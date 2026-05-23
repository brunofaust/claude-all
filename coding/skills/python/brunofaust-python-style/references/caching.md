# Caching patterns

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

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
            filtered_args = tuple(v for i, v in enumerate(args) if i not in _ignore)
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
