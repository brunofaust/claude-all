# External System Ownership

**Rule:** Every external system has exactly one owner class/module. All code that touches that system goes through the owner. No exceptions.

**External systems include:** any third-party API (Jira, GitHub, Stripe, etc.), any AWS service (S3, DynamoDB, SQS, etc.), any AI provider (OpenAI, Anthropic).

## Anti-pattern — direct SDK use outside owner

```python
# BAD: direct httpx outside the connector
import httpx


async def get_ticket_status(key: str) -> str:
    r = await httpx.get(f"https://x.atlassian.net/rest/api/3/issue/{key}")
    ...


# BAD: inline boto3 client
import boto3

s3 = boto3.client("s3")
s3.put_object(...)

# BAD: bypassing the connector with the SDK it wraps
from atlassian import Jira

jira = Jira(...)
jira.issue(key)
```

## Correct — single owner class

```python
# integrations/jira/client.py — THE single owner
class JiraClient:
    async def get_issue(self, key: str) -> Ticket: ...
    async def search_issues_jql(self, jql: str) -> Sequence[Ticket]: ...
    async def post_comment(self, key: str, body: str) -> None: ...

# Consumers:
from <project>.integrations.jira import JiraClient
ticket = await jira.get_issue("PROJ-123")
```

## Layering rule

- Third-party API connectors/clients in `integrations/<system>/` — only layer that touches those APIs.
- **AWS service wrappers in `core/aws/<service>.py`** — one file per service (`s3.py`, `sqs.py`,
  `dynamodb.py`, …), the only layer that touches `boto3`/`aiobotocore`. They share a `core/aws/base.py`
  (one `AWSClient` base + a process-wide aiobotocore session, so clients are reused across invocations).
  These wrappers are **settings-free** — they live in `core/` precisely because they take config as
  args, not by importing `settings` (see `project-structure.md`, "core is extractable").
- Do NOT confuse this with `aws_resources/` — that holds **deployable units** (Lambda handlers, ECS
  tasks) which *consume* the `core/aws` clients. Resource ≠ client wrapper.
- Services/handlers consume the client interface, never import the underlying SDK.
- Tests mock the client, not the SDK.

## Query surfaces are external systems — one owner per store surface

A **query surface** — a specific DB table (or logical entity), a search index, a
vector namespace, a cache keyspace — is an external system in exactly this sense:
every read and write against it is a store operation, and it gets **exactly one
module** that owns those operations. Callers **never assemble store access inline**;
they call the owner's functions and only build inputs / format outputs.

The granularity is the *surface*, not the whole engine. `PostgresClient` is not the
owner of the `orders` table any more than "the network" owns an API — the `orders`
store module is. One module per table/index/namespace, each exposing a query per
access pattern (`get_order(id) -> Order`, `list_open_orders(...) -> Sequence[Order]`).

**The trigger is the SECOND call site, not the third.** The Rule of Three is about
*uncertain* similarity; a second place hand-building the same store access is
*structurally certain* sameness — same table, same columns, same filter shape — so
there is nothing to wait to learn. Extract the owner when the second caller appears.
(Reconciliation → [`architecture.md`](architecture.md), "Rule of Three vs the
two-copy trigger".)

```python
# BAD: two call sites each hand-assembling the same store access
# site A
rows = await db.query(select(orders_t).where(orders_t.c.status == "open"))
open_orders = [Order.model_validate(r._mapping) for r in rows]
# site B (drifts the moment one is edited and the other isn't)
rows = await db.query(select(orders_t).where(orders_t.c.status == "open"))
...

# GOOD: one owner; callers only build inputs and format outputs
# stores/orders.py — THE owner of the orders surface
async def list_open_orders() -> Sequence[Order]:
    rows = await db.query(select(orders_t).where(orders_t.c.status == "open"))
    return [Order.model_validate(r._mapping) for r in rows]
```

## Structural duplication — the clone detector cannot see it

Token-similarity duplication gates (`jscpd`, codecongruence-style — see
[`enforcement.md`](enforcement.md), "Bounded copy-paste duplication") catch
**copy-paste**: same *text*. They are blind to **structural** duplication —
*same responsibility, different text*: three call sites each hand-assembling the
same multi-store pipeline with different variable names, helper spellings, and
ordering. No token window matches, so the gate stays green at every threshold while
the same logic lives in three places.

Real incident: a multi-store read (a DB table + a search index + a cache) was
hand-assembled at **three** call sites; collapsing them into a single owner module —
callers only build the query inputs and format the results — removed **~1,700 lines**.
The clone detector had never flagged any of it, because no two call sites shared
enough literal text.

**Find it by responsibility, not by text.** No tool substitutes for the review
question, so ask it deliberately — especially when a PR adds a **new call site that
touches an existing store or API**:

> Who else already talks to this store / index / API? Should this caller be calling
> an owner that already exists (or should exist) instead of assembling the access
> itself?

A new call site reaching a store directly is the single highest-yield place to catch
a missing owner. Make it a standing review checkpoint, and re-sweep periodically by
store surface ("everything that reads the `orders` table") rather than by diff.

## Enforcement — ruff `banned-api` config

```toml
[tool.ruff.lint.flake8-tidy-imports.banned-api]
"httpx".msg = "Use the owning connector class. Allowed only in src/*/integrations/**"
"boto3".msg = "Use the core/aws/<service>.py wrapper. Allowed only in src/*/core/aws/**"
"aiobotocore".msg = "Use the core/aws/<service>.py wrapper. Allowed only in src/*/core/aws/**"
"botocore".msg = "Use the core/aws wrapper + its semantic exceptions (core/aws/exceptions). Allowed only in src/*/core/aws/**"
"atlassian".msg = "Use JiraClient or ConfluenceClient"
"asyncio.to_thread".msg = "Use run_in_thread() — the single owner of the thread-offload seam"
"subprocess".msg = "Use the owned run_exec()/run_shell() wrapper (argv list, never a shell string). Allowed only in scripts/**"

[tool.ruff.lint.per-file-ignores]
"src/*/integrations/**" = ["TID251"]
"src/*/core/aws/**" = ["TID251"]      # the boto3/aiobotocore owners live here
```

## Semantic exceptions — own the SDK's error type too

Owning the SDK isn't only about the *client*; own its *exceptions*. A `core/aws` wrapper catches the
raw `botocore.ClientError` and re-raises a typed error it owns (`dynamodb.ConditionalCheckFailed`,
`s3.ObjectNotFound`, …) via a small `translating(code_map, default)` helper — so consumers catch typed
errors and never import `botocore` (that's why `botocore` is in the ban above). Full pattern +
`translating()` helper: see `error-handling.md` → "AWS errors: owner-translated semantic exceptions".

## Audit recipe

```bash
rg -n "import httpx|from httpx|boto3\.client|from atlassian|^import github|aiobotocore|from botocore|import botocore" \
  src --type py | rg -v "src/[^/]+/integrations/|src/[^/]+/core/aws/"
```

Empty output = clean. Any line returned = a leak to fix.

## When the owner pattern is overkill

- One-shot scripts (`scripts/*.py`) — direct SDK / `subprocess` use is fine (the
  `banned-api` rules above carve out `scripts/**`).
- In application code, even stdlib side-effecting seams (`subprocess`, the
  thread-offload via `asyncio.to_thread`) get a single owner — `run_exec()` /
  `run_shell()` and `run_in_thread()` respectively. Argv lists, never shell strings.
- Test code that needs to construct fake SDK responses — keep SDK-shaped fixtures co-located with tests.
