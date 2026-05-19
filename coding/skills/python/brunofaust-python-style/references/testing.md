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

