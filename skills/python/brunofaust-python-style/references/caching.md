# Caching patterns

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

### Caching Pattern

Use **cachebox** — a Rust-backed caching library that is internally thread-safe and natively supports async functions. No external locks or custom async wrappers needed.

Use module-level `TTLCache` (preferred) or `LRUCache` instances with the `@cachebox.cached` decorator for both sync and async functions.

```python
import cachebox
from cachebox import TTLCache

get_configuration_cache: TTLCache = TTLCache(maxsize=10, global_ttl=CACHE_1_HOURS)
get_data_cache: TTLCache = TTLCache(maxsize=10, global_ttl=CACHE_1_HOURS)


@cachebox.cached(get_configuration_cache)
async def get_configuration(config_name: str) -> Mapping[str, Any]:
    """Retrieve application configuration with caching."""
    ...


@cachebox.cached(get_data_cache)
async def get_data(data_name: str) -> Mapping[str, Any]:
    """Retrieve application data with caching."""
    ...
```

- Define one cache per function at the module level
- cachebox is internally thread-safe (Rust mutex) — **no external locks needed**
- `@cachebox.cached` works identically for sync and async — **no custom async decorator needed**
- Use appropriate TTL durations: `CACHE_24_HOURS` for stable data, shorter for volatile data (e.g. `CACHE_1_HOURS`, `CACHE_12_HOURS`)

#### Instance method caching

Instance methods need a callable that returns the cache per-instance (or a shared module-level cache):

```python
get_method_value_cache: TTLCache = TTLCache(maxsize=10, global_ttl=CACHE_1_HOURS)


class DataService:
    @cachebox.cached(lambda self: get_method_value_cache)
    async def get_value(self, key: str) -> Mapping[str, Any]:
        """Retrieve value with caching."""
        ...
```

Or with an instance-level cache (isolated per object):

```python
class DataService:
    def __init__(self) -> None:
        self._cache: TTLCache = TTLCache(maxsize=10, global_ttl=CACHE_1_HOURS)

    @cachebox.cached(lambda self: self._cache)
    async def get_value(self, key: str) -> Mapping[str, Any]:
        """Retrieve value with caching."""
        ...
```

#### Key generation

By default cachebox hashes positional args. For complex or unhashable arguments, pass a `key_maker`:

```python
from cachebox import make_hash_key, make_typed_key

@cachebox.cached(get_data_cache, key_maker=make_hash_key)
async def get_data(filters: Mapping[str, Any]) -> Sequence[Any]:
    """Retrieve filtered data with caching."""
    ...
```

Use `make_typed_key` when `1` and `True` must resolve to different cache entries.

#### Cache algorithms

| Class        | Eviction            | Use when                              |
| ------------ | ------------------- | ------------------------------------- |
| `TTLCache`   | Time-based (global) | All cases with expiry — **default**   |
| `VTTLCache`  | Time-based (per-entry) | Entries need different TTLs        |
| `LRUCache`   | Least-recently-used | No expiry, bounded memory             |
| `LFUCache`   | Least-frequently-used | Frequency-weighted retention        |
| `FIFOCache`  | First-in-first-out  | Simple bounded queue                  |

#### Cache bypass

Skip the cache for a single call without invalidating it:

```python
result = get_configuration("my-config", cachebox__ignore=True)
```

#### Frozen (read-only) caches

Wrap a pre-populated cache to prevent further writes at runtime:

```python
from cachebox import Frozen, LRUCache

lookup_cache: LRUCache = LRUCache(maxsize=256)
# ... populate lookup_cache at startup ...
lookup = Frozen(lookup_cache)
```
