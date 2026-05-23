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

- Connectors/clients in `integrations/<system>/` — only layer that touches external APIs.
- AWS service wrappers in `aws_resources/<service>/` or `aws/<service>/` — only layer that touches `boto3`.
- Services/handlers consume the client interface, never import the underlying SDK.
- Tests mock the client, not the SDK.

## Enforcement — ruff `banned-api` config

```toml
[tool.ruff.lint.flake8-tidy-imports.banned-api]
"httpx".msg = "Use the owning connector class. Allowed only in src/*/integrations/**"
"boto3".msg = "Use the AWS service wrapper. Allowed only in src/*/aws_resources/**"
"aioboto3".msg = "Use the AWS service wrapper. Allowed only in src/*/aws_resources/**"
"atlassian".msg = "Use JiraClient or ConfluenceClient"

[tool.ruff.lint.per-file-ignores]
"src/*/integrations/**" = ["TID251"]
"src/*/aws_resources/**" = ["TID251"]
```

## Audit recipe

```bash
rg -n "import httpx|from httpx|boto3\.client|from atlassian|^import github" \
  src --type py | rg -v "src/[^/]+/integrations/|src/[^/]+/aws_resources/"
```

Empty output = clean. Any line returned = a leak to fix.

## When the owner pattern is overkill

- One-shot scripts (`scripts/*.py`) — direct SDK use is fine.
- Truly stdlib-only deps (no third-party SDK) — wrapping `subprocess` rarely pays off.
- Test code that needs to construct fake SDK responses — keep SDK-shaped fixtures co-located with tests.
