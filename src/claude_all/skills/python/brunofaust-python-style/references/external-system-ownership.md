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
