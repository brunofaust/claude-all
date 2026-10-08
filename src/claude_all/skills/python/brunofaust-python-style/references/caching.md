# Caching patterns

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

### Caching Pattern

Use **cachebox**, a Rust-backed caching library. It is internally thread-safe and supports async functions natively, so you need no external locks or custom async wrappers.

**cachebox is the only sanctioned in-process cache.** `functools.lru_cache` / `functools.cache` and
third-party caches (`cachetools`, `diskcache`, `aiocache`, `beaker`) are banned. An ad-hoc cache is
hidden, process-local, often unbounded state. It makes a function's result depend on call ORDER
(whether an earlier test or request already warmed the key). Under `pytest-xdist` that shows up as
tests that pass in one worker and fail in another, because each worker has its own warm or cold
copy. Enforce the ban in two halves, one per violation shape:
an import-linter `forbidden` contract bans the third-party imports, and a small AST checker bans the
`@functools.lru_cache` / `@functools.cache` decorators. import-linter cannot see decorators, and
`functools` itself must stay importable. **`functools.cached_property` is a permanent exception,**
not debt. It caches per instance, and it is the mechanism behind lazy settings groups
([config.md](config.md)).

### Where the cache lives — process-global vs per-run scope

Where a cache may live depends on **whether the cached value belongs to a tenant**:

| Cached value | Where the cache lives | Why |
| --- | --- | --- |
| **Tenant-free** (platform config, a public schema, a static lookup), or a single-tenant app | Process-global (module-level) `TTLCache` is acceptable | Every caller should see the same value, so warm reuse is a feature |
| **Tenant-bound** (anything derived from an org's config, credentials or data) in a multi-tenant app | A cache owned by the **per-invocation scope object**, built inside `main()` / the handler and dropped at the end of the run | A warm Lambda container or long-lived ECS service reuses the process for the **next tenant**. A module-level cache would serve tenant A's value to tenant B |

The second row is the rule we moved to after the warm-reuse leak. A module-level cache keyed on
everything *except* the tenant is a cross-tenant data leak. Cold-start tests never see it, because
it needs two tenants on one warm process. The fix is structural: if the cache dies with the run, no
other tenant can ever reach it. In a multi-tenant deploy unit, a per-run scope is the default. A
process-global cache must justify itself as tenant-free. See
[tenant-isolation.md §2](tenant-isolation.md) and the no-process-globals rule in
[architecture.md](architecture.md).

#### Process-global cache (tenant-free data only)

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

- One cache per function. Use a module-level cache **only for tenant-free data** (see the table above).
- cachebox is internally thread-safe (Rust mutex), so **no external locks are needed**.
- `@cachebox.cached` works the same for sync and async, so **no custom async decorator is needed**.
- Read TTLs and sizes from settings (`get_settings().cache.CONFIG_TTL_SECONDS`), never from a hard-coded constant.

#### Per-run scope cache (tenant-bound data — the multi-tenant default)

Construct the service, and its cache, inside the run's scope. It dies with the invocation:

```python
class TenantConfigService:
    """Built once per invocation from the parsed tenant scope; never at module level."""

    def __init__(self, org_id: PositiveId, ttl_seconds: int) -> None:
        self.org_id = org_id
        self.cache: TTLCache = TTLCache(maxsize=64, global_ttl=ttl_seconds)

    @cachebox.cached(lambda self: self.cache)
    async def get_value(self, key: str) -> TenantValue:
        ...


async def main(event: InvocationEvent) -> None:
    settings = get_settings()
    config = TenantConfigService(event.org_id, settings.cache.TENANT_TTL_SECONDS)
    ...  # use, then let it go out of scope with the run
```

If a tenant-bound cache truly has to outlive one run (an ECS service handling many tenants), the
tenant id must be part of the key, as a **positional-only** parameter so no caller can drop it.
See [tenant-isolation.md §2](tenant-isolation.md).

#### Key generation

By default cachebox hashes positional args. For complex or unhashable arguments, pass a `key_maker`:

```python
from cachebox import make_hash_key, make_typed_key

@cachebox.cached(get_data_cache, key_maker=make_hash_key)
async def get_data(filters: DataFilters) -> Sequence[DataRow]:
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
