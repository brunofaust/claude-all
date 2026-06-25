# Testing patterns — pytest, mocks, fixtures

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

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
1. **One assertion per test** when possible
1. **Use descriptive test names** that explain behavior
1. **Keep tests independent** and isolated
1. **Use fixtures** for setup and teardown
1. **Mock external dependencies** appropriately
1. **Parametrize tests** to reduce duplication
1. **Test edge cases** and error conditions
1. **Measure coverage** but focus on quality

### Anti-patterns — what NOT to do

Common pytest patterns Claude will default to that **violate this skill**. Each
has a specific replacement — use it.

| ❌ Don't do this                                             | ✅ Do this instead                                                                       | Why                                                                            |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `@pytest.mark.asyncio` on every async test                   | `asyncio_mode = "auto"` in pytest.ini + `pytest_collection_modifyitems` hook in conftest | One source of truth; never forget to mark a test                               |
| `unittest.mock.patch` / `mocker.patch` on a module attribute | Dependency injection — pass the dependency into the constructor                          | `mock.patch` is race-prone under `pytest-xdist`; DI is thread-safe and obvious |
| `mod._client = mock` (module-global assignment in test)      | Inject the client via fixture / factory                                                  | Race-prone under parallel test runs; banned by AST hook                        |
| `Mock()` / `MagicMock()` for typed objects                   | `polyfactory` / `factory_boy` factory for the concrete type                              | Real types catch contract drift; mocks happily accept anything                 |
| `scope="session"` for app / AWS clients                      | `scope="function"` (or `scope="module"` only when safe)                                  | Session-scoped state leaks between tests; MiniStack needs per-test isolation  |
| `monkeypatch.setattr(...)` without `MonkeyPatch.context()`   | `with MonkeyPatch.context() as mp: mp.setattr(...)`                                      | Explicit teardown; safe under parallel collection                              |
| `@pytest.fixture` with side-effects but no `yield` cleanup   | Always `yield` + cleanup, even for "harmless" fixtures                                   | Resource leaks compound under `-n auto`                                        |
| Mocking AWS with `moto` / `boto-mock` for integration tests  | MiniStack (Docker, managed by the project's pytest plugin)                               | Higher fidelity; catches real boto serialization bugs                          |
| `unittest.mock.patch` / `MagicMock` module-patching in `tests/` | `pytest-mock` (`mocker` fixture) only when DI is genuinely impossible; `from unittest.mock import AsyncMock` for protocol stubs is the one allowed import | Plugin gives auto-cleanup; stdlib `patch` is easy to forget to stop            |
| `assert x` with no message on complex objects                | `assert x, f"context: {x!r}"` or `pytest.fail(...)`                                      | Failure logs are unreadable otherwise                                          |
| `time.sleep(N)` to wait for an async event                   | `await asyncio.wait_for(...)` / `pytest-asyncio` + polling helper                        | sleeps make tests flaky and slow                                               |
| Catching `Exception` in tests to "be safe"                   | Let exceptions propagate; use `pytest.raises(SpecificError)`                             | Silently swallowing errors hides real bugs                                     |
| Hard-coded DB ids / keys (`customer_id=1`, `"TICK-1"`)       | Generate a fresh id per test (`uuid4`, factory sequence, `INSERT ... RETURNING`)         | Two tests reusing id `1` clobber each other under xdist → flaky               |
| Sharing a seeded row across tests (a global "test customer")  | Each test seeds its **own** rows; no cross-test data                                     | One test mutating shared data breaks another non-deterministically            |
| A child row pointing at another tenant's parent (shared FK)  | Every FK resolves within the **same** tenant the test created                            | Cross-tenant FK leakage hides isolation bugs and corrupts parallel runs       |
| Running the suite single-process (`-n0`) as the default       | `-n auto --dist worksteal` is the default; `-n0` only to debug                           | xdist is the isolation/concurrency **validator**, not just a speed-up         |
| `@pytest.mark.xdist_group(...)` to pin co-dependent tests together | Make each test self-contained so worksteal can scatter it anywhere                   | Grouping hides a test-depends-on-test bug instead of fixing it (rare exception — ask first) |

### Test data isolation — the flaky-test root cause

> These rules came out of a real debugging marathon: hours lost to "flaky" tests
> that were actually **shared-state** tests racing each other under `pytest-xdist`.
> A test is only flaky if it depends on data it doesn't own. Own your data and the
> flakiness disappears.

The contract, in four rules:

1. **Database ids are dynamic — never hard-coded.**
1. **Each test owns its own data — nothing shared between tests.**
1. **Foreign keys never cross tenants — a child row belongs to its parent's tenant.**
1. **The suite runs under `pytest-xdist` — concurrency is part of the test.**

#### Rule 1 — dynamic ids, never hard-coded

A literal id (`customer_id=1`, `"TICK-1"`, `tenant="acme"`) is a collision waiting
to happen: the moment two tests use it — or two xdist workers run the same test
file — they read and write the same row. Generate a fresh id for every record.

```python
# ❌ BAD — every test that uses customer 1 fights over the same row
await db.insert_customer(id=1, name="Test Customer")
await db.insert_order(id=1, customer_id=1, amount=100)


# ✅ GOOD — ids come from the database / a factory, unique per test
customer_id = await db.insert_customer(name="Test Customer")  # INSERT ... RETURNING id
order_id = await db.insert_order(customer_id=customer_id, amount=100)
```

Sources of dynamic ids, in order of preference:

- **DB-generated** — `INSERT ... RETURNING id` (identity / serial / UUID default).
  The database is the single source of truth for the key.
- **Factory sequences** — `factory_boy` `Sequence` / `polyfactory` auto-fields.
- **`uuid4()`** for client-generated keys (and natural keys: suffix with a short
  random token, e.g. `f"order-{uuid4().hex[:8]}"`, never a bare `"order-1"`).

#### Rule 2 — each test owns its data; nothing shared

Every test **creates the rows it needs and only touches those rows**. No
"well-known test customer" seeded once and reused; no test reading a row another
test wrote. Shared data means one test's mutation (or teardown) silently changes
another test's inputs — the textbook flaky test.

```python
# ❌ BAD — module/session fixture everyone mutates
@pytest.fixture(scope="session")
def shared_customer(db):
    return db.insert_customer(id=1, name="Shared")  # tests stomp on each other


# ✅ GOOD — function-scoped, each test gets its own freshly-seeded customer
@pytest.fixture
async def customer(db):
    cid = await db.insert_customer(name=f"cust-{uuid4().hex[:8]}")
    yield await db.get_customer(cid)
    await db.delete_customer(cid)  # own it, clean it up
```

- Fixtures that create data are **`scope="function"`** (see the anti-pattern table
  — session scope leaks).
- If two tests need "the same kind of" data, they each seed their own copy. Same
  *shape*, different *rows*.
- A test asserts only on rows it created — never `SELECT COUNT(*) FROM orders`
  (another worker's rows inflate it); scope the query to your own ids.

#### Rule 3 — foreign keys never cross tenants

In a multi-tenant schema, **a foreign key must resolve within the same tenant**.
Tenant A's order may not reference tenant B's customer. Sharing a row across
tenants in a fixture hides exactly the isolation bug your tests exist to catch,
and corrupts data when parallel tests assume their tenant is private.

```python
# ❌ BAD — one customer row reused across tenants; FK crosses the tenant boundary
shared_customer_id = 1
await db.insert_order(tenant_id="A", customer_id=shared_customer_id)
await db.insert_order(tenant_id="B", customer_id=shared_customer_id)  # B borrows A's customer


# ✅ GOOD — each tenant gets its own customer; every FK stays inside the tenant
tenant_a = await seed_tenant()
cust_a = await db.insert_customer(tenant_id=tenant_a.id, name="...")
await db.insert_order(tenant_id=tenant_a.id, customer_id=cust_a)  # same tenant

tenant_b = await seed_tenant()
cust_b = await db.insert_customer(tenant_id=tenant_b.id, name="...")
await db.insert_order(tenant_id=tenant_b.id, customer_id=cust_b)  # same tenant
```

**The seed simulates real data.** Production never shares a customer row across two
tenants, so the seed must not either. If a test needs a customer in tenant B,
**create a new customer row in tenant B** — don't reach for an existing one in
tenant A because it's convenient. Model the real-world cardinality (a tenant owns
its customers, a customer owns its orders) all the way down the FK chain.

#### Rule 4 — run under xdist (it's a correctness check, not just speed)

The suite runs `-n auto --dist worksteal` (see `pytest.ini` above) **by default**.
xdist isn't only a speed-up — it's the mechanism that *proves* rules 1–3 hold:

- **Concurrency validation.** Tests execute simultaneously across worker
  processes. A test that depends on shared/static data will collide with another
  worker and fail — surfacing the isolation bug that a serial run would hide.
- **Feature isolation.** Workers steal tests across files, so two unrelated
  features run side-by-side against the same database. Cross-feature data bleed
  shows up here.
- **`pytest-randomly`** on top randomises order, so a test that secretly depended
  on running after another fails loudly.

Practical consequences for writing tests under xdist:

- **Resource names unique per worker / per test.** MiniStack buckets, queues,
  tables, S3 prefixes — suffix with the test's dynamic id or
  `os.environ["PYTEST_XDIST_WORKER"]` so two workers don't share infra (see
  [§ MiniStack resource setup](#ministack-resource-setup)).
- **No reliance on global counts or ordering** — your assertions read only your
  own ids.
- **`-n0` is for debugging a single test, never the committed default.** If a test
  only passes at `-n0`, it has a hidden shared-state dependency — fix the test,
  don't pin the worker count.
- **Never reach for `@pytest.mark.xdist_group` to make a flaky test pass.**
  `xdist_group` forces every test in the named group onto the **same worker**, run
  in order — it's the marker people use when one test depends on another's state.
  That is the exact bug these rules exist to kill: it *hides* a
  test-depends-on-test coupling instead of fixing it. The fix is to make each test
  self-contained (own data, own ids, own resources) so `--dist worksteal` can
  scatter it to any worker in any order. Pinning tests together just relocates the
  flakiness — it doesn't remove it.

  **Treat the marker as a diagnostic, not a tool.** If you find yourself reaching
  for `xdist_group`, that is the signal your tests aren't isolated correctly —
  stop and fix the isolation (dynamic ids, per-test data ownership, per-test
  resource names), don't paper over it by forcing the tests onto one worker.

  **The rare exception — ask first, document why.** A *very* occasional case
  genuinely can't be split (e.g. a single contended external singleton with no
  per-test namespace). Before adding `xdist_group`, **ask the user**, and only
  proceed once you've explained to them *why* it's needed and why isolation isn't
  achievable here. Record that reason in a comment on the marker:

  ```python
  # xdist_group: APPROVED by <user> — <external resource> has no per-test namespace,
  # so these tests must serialise on one worker. Isolation not achievable here.
  @pytest.mark.xdist_group("legacy_global_singleton")
  async def test_...() -> None: ...
  ```

  No silent `xdist_group`. If it appears without an approval comment, treat it as a
  hidden shared-state bug and fix the test instead.
- **Driving global jobs from a test?** Scope them to the test's own tenant so an
  all-tenant sweep can't race the test — see
  [`scoped-processes.md`](scoped-processes.md).

#### Quick isolation checklist

- [ ] No literal ids — every key is DB-generated, factory-sequenced, or `uuid4`.
- [ ] Data-creating fixtures are `scope="function"` and clean up after themselves.
- [ ] Each test seeds its own rows; no test reads another test's data.
- [ ] Every FK resolves inside one tenant; no cross-tenant row sharing in seeds.
- [ ] Seed mirrors real cardinality — new row per tenant, never a borrowed one.
- [ ] Assertions scope to the test's own ids (no global `COUNT(*)`).
- [ ] MiniStack / external resource names are unique per test or per xdist worker.
- [ ] Suite passes under `-n auto` **and** `pytest-randomly` (not just `-n0`).
- [ ] No `@pytest.mark.xdist_group` unless user-approved with a documented reason comment.

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
- **AWS Mocking**: MiniStack (Docker container, managed by custom pytest plugin) — a LocalStack drop-in on the same `:4566` endpoint (see [§ MiniStack](#ministack--the-aws-emulator-localstack-drop-in))
- **Event Loop**: uvloop (session-scoped fixture)
- **Leak Detection**: pyleak for task and thread leak detection
- **Timeouts**: 5s per test, 30s per slow test, 60s per data/ministack test, 300s per session

#### pytest Plugins and Dependencies

- pyleak: identify async or thread leaks
- pytest-asyncio: async tests
- pytest-cov: coverage
- pytest-dotenv: load environment variables
- pytest-rerunfailures: rerun failed
- pytest-timeout: timeout test
- pytest-unordered: order-insensitive collection comparisons (use pytest-randomly for random test order)
- pytest-xdist: parallel execution
- python-on-whales: control Docker
- freezegun: freezes the datetime
- coverage: coverage
- filelock: lock based on file (to lock between xdist processes)
- (no LocalStack-specific client — point boto3 at MiniStack via `endpoint_url` / `AWS_ENDPOINT_URL=http://localhost:4566`)
- hypothesis: random value generator for tests

#### pytest.ini Configuration

```ini
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = session
pythonpath = .
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
    ministack: tests that expect a MiniStack environment (S3, DynamoDB, SQS, SNS, etc.)
```

#### Coverage threshold (pyproject.toml)

Coverage is a CI gate, not a vanity metric — fail the build below threshold so
PRs can't merge with uncovered new code.

```toml
[tool.pytest.ini_options]
addopts = """
    --cov=src
    --cov-report=term-missing
    --cov-report=html
    --cov-branch
    --cov-fail-under=80
"""

[tool.coverage.report]
exclude_also = [
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
    "@abstractmethod",
    "if __name__ == .__main__.:",
]
```

Run with: `uv run pytest --cov` — exits non-zero if coverage < 80%.

#### Selective marker runs

```bash
# Local fast loop — skip slow + ministack tests
uv run pytest -m "not slow and not ministack"

# Run only unit tests (fast CI lane)
uv run pytest -m unit

# Run integration + data layer (slow CI lane)
uv run pytest -m "integration or data or ministack"

# CI matrix example: split fast/slow into separate jobs
# job-fast:  pytest -m "not slow and not ministack" --cov-fail-under=80
# job-slow:  pytest -m "slow or ministack"
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
def test_create_user_with_valid_data_returns_user(): ...


def test_create_user_with_duplicate_email_raises_conflict(): ...


def test_get_user_with_unknown_id_returns_none(): ...


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
@pytest.mark.ministack  # Tests requiring MiniStack (S3, DynamoDB, SQS, SNS, etc.)
@pytest.mark.data  # Full data pipeline tests (probably uses MiniStack)
@pytest.mark.slow  # Slow-running tests
@pytest.mark.timeout(5)  # Override per-test timeout
@pytest.mark.no_leaks_local(threads=False)  # Leak detection (exclude thread checks)
def example_test() -> None: ...


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
    """Verify all declared attributes exist."""
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

    # check if the mock was called once with a specific parameter
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
    client._client,
    "generate_url",
    AsyncMock(return_value="http://download/url"),
)

# Multiple return values (pagination simulation)
monkeypatch.setattr(
    client._client,
    "list_objects_v2",
    AsyncMock(
        side_effect=[
            {"Contents": [{"Key": "file1.csv"}], "IsTruncated": True},
            {"Contents": [{"Key": "file2.csv"}], "IsTruncated": False},
        ]
    ),
)

# Exception simulation
monkeypatch.setattr(
    client._client,
    "get_item",
    AsyncMock(side_effect=ClientError({"Error": {"Code": "404"}}, "get")),
)
```

#### Module-Level MonkeyPatching

For global mocks that apply across all tests (e.g., replacing config loading with local file reads):

```python
# In conftest.py — session-scoped patching with explicit undo


async def _mock_get_configuration(cls, config_name: str) -> Any:
    """Replace remote config loading with local JSON files."""
    file = f"{os.path.dirname(__file__)}/configuration/{config_name}.json"
    async with aiofiles.open(file) as fp:
        content = await fp.read()
    return orjson.loads(content)


@pytest.fixture(autouse=True, scope="session")
def _patch_configuration() -> Iterator[None]:
    """Apply the global mock for the whole session, undone on teardown."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "some_class.get_configuration",
            _mock_get_configuration,
        )
        yield
```

### Data Tests

Data tests verify the full pipeline end-to-end (probably using MiniStack).

```python
@pytest.mark.data
async def test_step_1_load_first_file() -> None:
    """Load initial source file and verify target output."""

    pipeline = await create_pipeline()

    # 1. Create parquet file
    await create_parquet(
        filename="file1.parquet", data=[{"id": 1, "name": "order-001", "amount": 100}]
    )

    # 2. Run pipeline for the parquet
    await pipeline(filename="file1.parquet")

    # 3. Verify target data
    lf = await get_orders()

    expected_lf = pl.LazyFrame(...)
    assert_frame_equal(lf.collect(), expected_lf.collect())

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
            storage._client,
            "list_objects_v2",
            AsyncMock(
                side_effect=[
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
                ]
            ),
        )
        res = await storage.get_files(
            bucket="my-bucket",
            prefix="prefix/",
            suffix=".parquet",
        )
        keys = [file["Key"] for file in res]

        assert "prefix/file2.parquet" in keys
        assert "prefix/file3.parquet" in keys
        assert "prefix/file1.csv" not in keys
```

### MiniStack — the AWS emulator (LocalStack drop-in)

Integration / data tests run against **MiniStack** (`ministack.org`), a free,
open-source LocalStack replacement that serves every AWS service on the **same
`:4566` endpoint**. It is a true drop-in: point boto3 at it with
`endpoint_url="http://localhost:4566"` (or `AWS_ENDPOINT_URL`) — no code change
from a LocalStack setup. Use the default image for the common services; use the
**`:full`** image when you need S3 Tables / Athena (DuckDB catalog).

#### Lambda execution — pick an executor, mind real-runtime parity

MiniStack can run a Lambda three ways (`LAMBDA_EXECUTOR`). The choice trades
**container parity**, **speed**, and **log visibility** — decide per project:

| `LAMBDA_EXECUTOR`        | How it runs the handler                                     | Trade-off                                                                                                                                                                                                                                                  |
| ------------------------ | ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `local`                  | in MiniStack's own process (no sibling container)           | Simplest — every Lambda's stdout/stderr lands in the MiniStack server log, nothing leaks. **Loses real-runtime parity:** your code runs under MiniStack's bundled interpreter, so an interpreter- or C-ext-only construct (`orjson.orjson`, parenthesized `except (A, B)`) can break. Don't set `LAMBDA_STRICT` here. |
| `docker-reuse`           | a warm container **pool**, reused for `LAMBDA_WARM_TTL_SECONDS` | Curbs the per-invoke container leak and keeps `docker logs <fn>-<uuid>` readable for the TTL window — **but a stale warm container can serve the wrong runtime**: a pool first spun under MiniStack's bundled interpreter keeps running your code under it (silent version corruption).                              |
| `docker` (strict parity) | a **fresh** `--rm` runtime container per invoke             | True parity — each invoke is your real image/interpreter. Costs a per-invoke cold start (**~3 s/lambda in our tests — not negligible**; weigh it against e2e fan-out). Containers are ephemeral: catch logs mid-invoke, or via the server log. Pair with `LAMBDA_STRICT=1`.                                          |

**Why we run `docker` + `LAMBDA_STRICT=1`:** `docker-reuse` was the first pick (to
curb the container leak), but its stale warm pool ran our newer-Python code under
MiniStack's older bundled interpreter and choked (`No module named
'orjson.orjson'`; *"multiple exception types must be parenthesized"*). Switching to
`LAMBDA_EXECUTOR=docker` gives a fresh real-runtime container per invoke;
`LAMBDA_STRICT=1` forbids MiniStack's silent in-process fallback — a missing
container runtime then surfaces loudly as `Runtime.DockerUnavailable` instead of
quietly running your code under the wrong interpreter. The leak `docker-reuse` was
meant to solve is handled instead by reaping orphaned runtime containers (by
ancestor image) + `LAMBDA_DOCKER_FLAGS=-m 512m` + `LAMBDA_ACCOUNT_CONCURRENCY`.

| Env var (compose `environment:`) | Value     | Why                                                                                              |
| -------------------------------- | --------- | ------------------------------------------------------------------------------------------------ |
| `LAMBDA_EXECUTOR`                | `docker`  | Fresh real-runtime container per invoke — strict parity (see trade-off table above)              |
| `LAMBDA_STRICT`                  | `1`       | Disable the in-process fallback; a missing runtime errors as `Runtime.DockerUnavailable` (default `0`) |
| `LAMBDA_DOCKER_FLAGS`            | `-m 512m` | Per-spawned-container memory cap (`-m` is whitelisted)                                            |
| `LAMBDA_ACCOUNT_CONCURRENCY`     | `~cpu/2`  | Bound concurrent runtimes to host headroom so a fan-out burst can't spawn unbounded containers — size it `cpu/2` (simplest) or ~`RAM_GB/3` given the `-m 512m` per-container cap |
| `LAMBDA_WARM_TTL_SECONDS`        | `90`      | *(`docker-reuse` only)* reap idle warm containers fast (the default ~900s pins RAM)               |
| `MINISTACK_WORKER_THREADS`       | `16`      | Trim the oversized default 64-thread sync-offload pool                                            |
| `PERSIST_STATE`                  | `0`       | No persistence — the provisioner re-creates all resources on each start                          |

**Pin the Lambda runtime to your codebase's Python.** MiniStack runs a function
under a default/bundled interpreter unless told otherwise — so a 3.14 codebase
must declare it explicitly, or you hit the same wrong-Python failures as the
`docker-reuse` warm pool. Pin it **per function** in the `CreateFunction` call:

```python
client.create_function(
    FunctionName="myapp-local-worker",
    Runtime="python3.14",  # match the codebase — don't inherit MiniStack's default
    Handler="handler.main",
    ...,
)
```

(Some MiniStack versions may also expose a server-level default-runtime env var —
check your version; the per-function `Runtime` is the reliable, version-independent
way to pin it.)

A service-level compose `mem_limit` bounds **only** the MiniStack server process.
The spawned Lambda/ECS runtimes are **sibling** host-Docker containers (their own
cgroups) — cap *their* memory with `LAMBDA_DOCKER_FLAGS`, not `mem_limit`.

#### Reading MiniStack logs after an e2e run

A failed run surfaces in pytest only as a thin assertion — a `batchItemFailures`
count, a DLQ message, a `0 processed`. The **root cause** (the exception, an
`AccessDeniedException`, a `Could not parse SQLAlchemy URL`, …) is in CloudWatch,
inside MiniStack. Keep the stack up after the run with `DISABLE_DOCKER_DOWN=1`
*(our working flag — it keeps containers/logs alive through teardown; not in the
published config reference, so verify it against your MiniStack version)* so the
logs survive, then scan them through the `:4566` endpoint:

```bash
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
EP=http://localhost:4566

# list log groups
aws --endpoint-url=$EP logs describe-log-groups --query 'logGroups[].logGroupName' --output text
# tail one function
aws --endpoint-url=$EP logs tail /aws/lambda/myapp-local-worker --since 2h
# scan ALL lambdas for errors after a run
for g in $(aws --endpoint-url=$EP logs describe-log-groups \
    --query 'logGroups[?starts_with(logGroupName,`/aws/lambda/`)].logGroupName' --output text); do
  echo "=== $g ==="
  aws --endpoint-url=$EP logs tail "$g" --since 1h \
    | grep -iE '"level": *"error"|ERROR|Exception|AccessDenied|Traceback|batchItemFailures|Could not parse'
done
```

Step Functions logs land under `/aws/vendedlogs/states/<state-machine>`. Raise the
emulator's **own** verbosity with `LOG_LEVEL=DEBUG` (values `DEBUG|INFO|WARNING|ERROR`,
default `INFO`) when MiniStack itself — not your handler — is misbehaving.

**Reading these logs via an agent:** the real-AWS `cloudwatch-inspector` agent
targets an `AWS_PROFILE`; for MiniStack pass the **local endpoint explicitly**
(`--endpoint-url=http://localhost:4566` + `test`/`test` creds) instead of a profile.

#### Known gaps — re-check against the *current* version before relying on one

MiniStack ships point releases every 1–3 days, so a gap today may be closed
tomorrow. **Before you architect a workaround around a missing feature, verify
it's still missing in the version you run** (`ministack.org/docs` + the GitHub
changelog).

| Gap (as last verified)                                                                                                       | Impact / workaround                                                                                                                                                                       |
| ---------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Step Functions native integrations** — `ecs:runTask.sync`, the `lambda:invoke` `Payload` envelope, and JSONPath over DynamoDB-typed data are unreliable | Deploy the **real ASL**, but drive the SFN tail **in-process** in the test: call the same handlers the state machine would and replace only the AWS-managed *wiring* — every product component stays real |
| **Bedrock — not emulated**                                                                                                   | Run a **mock Bedrock endpoint** with deterministic responses (converse text, seeded embeddings, rerank); point the client at it via an env-gated base URL (empty → real Bedrock)         |
| **EventBridge cron / scheduled rules not auto-triggered**                                                                    | Invoke the scheduled handler directly from the test driver instead of waiting on the rule to fire                                                                                         |
| **IAM stored but never evaluated** — every call succeeds regardless of policy                                                | IAM-deny paths can't be exercised locally; cover them against real AWS                                                                                                                    |
| **CloudWatch alarms don't dispatch actions**                                                                                 | Assert on the metric data, not on alarm-triggered side effects                                                                                                                            |

**Env-gate every local-only affordance** so production is unchanged when the var
is absent: `AWS_ENDPOINT_URL_*` empty → real service; `ALLOW_INSECURE_*` unset →
strict. The mock-Bedrock base URL, the `:4566` endpoint override, and any
insecure-URL allowance must all read empty/false in prod.

### MiniStack resource setup

1. Resource names must be unique across tests to avoid collisions with pytest-xdist workers.
1. Create test-specific resources inside the test.
1. Create SHARED resources in parallel during test session setup using `asyncio.TaskGroup`:

```python
async def setup_ministack_resources() -> None:
    """Create all AWS resources needed for tests.

    Uses TaskGroup with a semaphore to create resources in parallel
    while respecting MiniStack's concurrency limits.
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
    early_config: Any,
    parser: Any,
    args: list[str],
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


@pytest.fixture(
    scope="session",
    params=[{"database_url": "postgresql://localhost/test", "api_key": "test-key", "debug": True}],
)
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


@pytest.mark.parametrize(
    "email,expected",
    [
        ("user@example.com", True),
        ("test.user@domain.co.uk", True),
        ("invalid.email", False),
        ("@example.com", False),
        ("user@domain", False),
        ("", False),
    ],
)
def test_email_validation(email, expected):
    """Test email validation with various inputs."""
    assert is_valid_email(email) == expected


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (2, 3, 5),
        (0, 0, 0),
        (-1, 1, 0),
        (100, 200, 300),
        (-5, -5, -10),
    ],
)
def test_addition_parameterized(a, b, expected):
    """Test addition with multiple parameter sets."""
    from test_calculator import Calculator

    calc = Calculator()
    assert calc.add(a, b) == expected


# Using pytest.param for special cases
@pytest.mark.parametrize(
    "value,expected",
    [
        pytest.param(1, True, id="positive"),
        pytest.param(0, False, id="zero"),
        pytest.param(-1, False, id="negative"),
    ],
)
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
# All tests (10 parallel workers)
uv run pytest -n10

# Without data/slow/ministack tests (quick check)
uv run pytest tests -m "not slow and not data and not ministack"

# Single test (disable xdist for cleaner output)
uv run pytest tests -n0

# Validate test collection after creating new tests
uv run pytest tests --collect-only
```

## Test Patterns — factories, DI, mirrored structure

**Rule:** Tests use factories, mirror `src/` structure, and never assign module globals.

### Factory pattern

Use `polyfactory` for Pydantic, `factory_boy` for dataclasses.

```python
# tests/factories/ticket.py
from polyfactory.factories.pydantic_factory import ModelFactory
from myproject.domain.models.ticket import Ticket


class TicketFactory(ModelFactory[Ticket]):
    __model__ = Ticket
    summary = "Default ticket summary"


# Usage in test
def test_extract():
    ticket = TicketFactory.build(comments=[])  # only override what matters
    assert process(ticket).status == "ok"
```

### Anti-pattern — dict fixture sprawl

```python
# BAD
def _make_task(**overrides):
    defaults = {"key": "PROJ-1", "summary": "...", "comments": []}  # ... etc.
    defaults.update(overrides)
    return defaults
```

### Anti-pattern — module-global mocks

```python
# BAD: poking module globals in tests (races under parallel pytest-xdist)
def test_pii():
    from myproject.features.pii_detection import service

    service._comprehend_client = mock_client  # racy, fragile
```

### Correct — dependency injection

```python
# In source
class PiiDetector:
    def __init__(self, comprehend_client: ComprehendClient): ...


# In test
def test_pii():
    detector = PiiDetector(comprehend_client=mock_client)
```

### Directory structure

Mirror `src/`:

```
src/myproject/features/pii_detection/service.py
tests/unit/features/pii_detection/test_service.py
```

### Test categories

- `tests/unit/` — pure logic, no I/O, fast
- `tests/integration/` — MiniStack, real DB, real connectors with VCR cassettes
- `tests/e2e/` — full workflow execution

### Rules

1. Every new file in `src/myproject/features/` must have a matching test file.
1. No `_mod._client = mock` patterns.
1. Use `pytest-randomly` to detect order-dependent tests.
1. `--dist worksteal` is fine if tests are properly isolated.

### Enforcement

- `skill_enforcer.py` rule `test_mirrors_src` — checks every `src/.../*.py` has a matching `tests/unit/.../test_*.py`.
- AST hook bans `<mod>._xxx = ...` assignments in test files.
- Coverage threshold check pre-push.
