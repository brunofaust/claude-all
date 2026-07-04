# Error handling — patterns + rationale

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

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

# Pattern 4b: Multiple exceptions in one handler (parenthesised tuple)
# On the 3.11–3.13 baseline use a parenthesised tuple. PEP 758's paren-less
# form (`except ConnectionError, TimeoutError:`) is 3.14+ only, and even
# there it is disallowed with `as` — parentheses are always required when
# binding the exception (`except (ConnectionError, TimeoutError) as e:`).
try:
    process()
except (ConnectionError, TimeoutError) as e:
    logger.warning("Transient failure, will retry", error=str(e))
    raise
except (ValueError, TypeError) as e:
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
        logger.warning("table_not_found", table=table)
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

# Pattern 6: TaskGroup with ExceptionGroup handling
try:
    async with asyncio.TaskGroup() as tg:
        for item in items:
            tg.create_task(_process_item_do(item))
except* (ConnectionError, TimeoutError) as eg:
    for e in eg.exceptions:
        logging.warning(f"Transient error: {type(e).__name__}-{e}")
except* (ValueError, TypeError) as eg:
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

#### AWS errors: owner-translated semantic exceptions (consumers never touch botocore)

Pattern 3 above (`except ClientError` + an `Error.Code` string check) is how the **owner**
(`core/aws/<service>.py`) inspects an AWS error — but **consumers must not** import botocore or match
raw code strings. Instead, the owner **translates** botocore `ClientError` into a typed exception
hierarchy it owns, and callers catch that. This lets the `banned-api` ban cover `botocore` too (see
`external-system-ownership.md`), so a raw `ClientError` never escapes `core/aws/`.

Put the base + a translation helper in `core/aws/exceptions.py`:

```python
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from botocore.exceptions import ClientError


class AwsError(Exception):
    """Base for every semantic error a core.aws owner raises."""

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code  # originating AWS Code, for the rare caller that must branch after catching


@contextmanager
def translating(code_map: Mapping[str, type[AwsError]], *, default: type[AwsError]) -> Iterator[None]:
    """Convert a botocore ClientError into the mapped (or default) AwsError.

    A *sync* context manager is correct around an ``await``: the wrapped coroutine's
    exception surfaces through ``__exit__`` after the await resolves. Unmapped codes
    fall back to ``default`` (the service base), so the owner NEVER leaks a raw ClientError.
    """
    try:
        yield
    except ClientError as e:
        code = str(e.response.get("Error", {}).get("Code", ""))
        raise code_map.get(code, default)(str(e), code=code) from e
```

Each service module owns its errors + a code map and wraps its client calls:

```python
# core/aws/dynamodb.py
class DynamoDbError(AwsError): ...
class ConditionalCheckFailed(DynamoDbError): ...

# module-level (never a `_`-prefixed name — see visibility.md)
DDB_ERROR_CODES: Mapping[str, type[DynamoDbError]] = {
    "ConditionalCheckFailedException": ConditionalCheckFailed,
}

class AsyncDynamoDB(AWSClient):
    async def put_item(self, table_name, item, condition_expression=None) -> None:
        client = await self._get_client()
        kwargs = {"TableName": table_name, "Item": to_dynamodb(item)}
        if condition_expression:
            kwargs["ConditionExpression"] = condition_expression
        with translating(DDB_ERROR_CODES, default=DynamoDbError):
            await client.put_item(**kwargs)
```

Consumers stay botocore-free — typed catch, no `Error.Code` string:

```python
from myapp.core.aws.dynamodb import AsyncDynamoDB, ConditionalCheckFailed

try:
    await AsyncDynamoDB().put_item(table, item, condition_expression="attribute_not_exists(pk)")
    return True                       # first writer wins
except ConditionalCheckFailed:        # NOT: except ClientError + code == "ConditionalCheckFailedException"
    return False                      # idempotent claim already taken
```

Rules:

- `translating()` **always** raises an `AwsError` subclass (mapped → specific; unmapped → service base
  like `S3Error`). A "catch-any" caller then catches the service base or `AwsError` — never `ClientError`.
- The ban keys are `boto3` / `aiobotocore` / `botocore` (owner folders exempt via `per-file-ignores`).
  `botocore.exceptions` is covered; `botocore.exceptions.ClientError` may still be caught *inside* the
  owner. A consumer importing `botocore` is a lint failure.
- If a caller reaches a raw client (`_get_client()`) for an op the wrapper doesn't expose, **add the
  owner method** (with `translating()` inside) rather than catching `ClientError` at the call site —
  this is a common latent smell the migration flushes out.
- Connectivity errors (`BotoCoreError`) are a *sibling* of `ClientError`, not caught by `translating()`.
  If callers relied on catching them, have the owner absorb `BotoCoreError` into its service base too.

#### Common Rationalizations Against `suppress()`

| Excuse                                                | Reality                                                                                                                                             | Counter                                                                                                                                        |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| "suppress() is too implicit/magic"                    | `suppress(FileNotFoundError)` explicitly says "ignore this." Try/except + `pass` requires a comment to infer intent. `suppress()` is MORE explicit. | Grep for `suppress(FileNotFoundError)` across the codebase. Compare to grepping for `pass`.                                                    |
| "I prefer try/except so readers see what's happening" | Readers must infer from a comment that the exception is intentional. Code intent is locked in at the call site with `suppress()`.                   | Ask: "Does try/except + `pass` communicate intent better than `with suppress(FileNotFoundError):`?" The answer is no.                          |
| "What if more statements get added to this block?"    | Then you should use try/except. But TODAY'S code should be written for TODAY'S scope, not hypothetical future code.                                 | Refactor when scope changes. Don't pre-emptively use try/except for code that might change. Overfitting to unknown futures creates worse code. |
| "My team doesn't know suppress()"                     | True for the first three uses. False by the fourth. Training takes 2 minutes.                                                                       | Use it consistently; document in code review that `suppress()` is the standard for single-statement expected exceptions.                       |
| "suppress() doesn't support logging/side effects"     | Correct — that's why try/except exists. If you need logging, use try/except.                                                                        | Ask: "Do we need to log this exception?" If yes, try/except. If no, suppress().                                                                |

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
        structlog.dev.ConsoleRenderer(),  # Switch to JSONRenderer() in prod
    ],
)
```

This pairs well with the dependency injection pattern — define a `Logger` Protocol
and inject structlog in production, a null logger in tests.

#### Map Errors to Standard Exceptions

Use Python's built-in exception types appropriately.

| Failure Type        | Exception           | Example                  |
| ------------------- | ------------------- | ------------------------ |
| Invalid input       | `ValueError`        | Bad parameter values     |
| Wrong type          | `TypeError`         | Expected string, got int |
| Missing item        | `KeyError`          | Dict key not found       |
| Operational failure | `RuntimeError`      | Service unavailable      |
| Timeout             | `TimeoutError`      | Operation took too long  |
| File not found      | `FileNotFoundError` | Path doesn't exist       |
| Permission denied   | `PermissionError`   | Access forbidden         |

## Error Handling Discipline — no silent swallow

**Rule:** No silent exceptions. No `log.debug` inside `except`. Every caught exception must either be re-raised with context or logged at `warning`/`error` with structured context.

### Anti-patterns

```python
# BAD: bare except, no context
try:
    process(x)
except Exception:
    pass

# BAD: debug-level swallowing
try:
    fetch_related(ticket)
except Exception as e:
    log.debug("failed to fetch related", error=str(e))  # vanishes in prod

# BAD: catching too broad
try:
    parse_json(s)
except Exception:
    return None
```

### Correct patterns

```python
# GOOD: specific exception, structured log, re-raise or convert
try:
    parse_json(s)
except json.JSONDecodeError as e:
    log.warning("invalid json payload", payload_len=len(s), error=str(e))
    raise InvalidPayloadError(f"could not parse: {e}") from e

# GOOD: external API error, downgrade to None with explicit warning
try:
    parent = await jira.get_issue(parent_key)
except JiraNotFoundError:
    log.warning("parent ticket missing", parent_key=parent_key)
    parent = None
except JiraRateLimitError:
    raise  # propagate for retry

# GOOD: defensive catch with explicit reason and metric
try:
    enrich_with_ai_summary(ticket)
except AnthropicAPIError as e:
    log.error("ai_summary_failed", ticket_key=ticket.key, error=str(e))
    metrics.increment("ai_summary.failure")
    # continue without summary — degraded mode is intentional
```

### Rules

1. Never `except Exception: pass`.
1. Never `log.debug` inside `except`. Use `warning` minimum.
1. Catch the narrowest exception class possible.
1. Include structured context (ids, keys, etc.) in every log.
1. Use `raise ... from e` when converting exceptions.
1. Document degraded modes in code comments when intentionally swallowing.

### Enforcement

- Ruff: `BLE001`, `TRY002`, `TRY003`, `TRY004`, `TRY200`, `TRY201`, `B904`.
- `skill_enforcer.py` rule `no_debug_in_except` — bans `log.debug` inside `except` blocks. See `references/enforcement.md`.
