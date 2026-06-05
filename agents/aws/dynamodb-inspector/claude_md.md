### Command dispatch — DynamoDB reads → `dynamodb-inspector` (Haiku, read-only)

| Command | Agent |
|---|---|
| `aws dynamodb get-item/query/scan/describe-table/list-tables` | `dynamodb-inspector` |

Anti-patterns:

- `Bash(aws dynamodb query ...)` / `Bash(aws dynamodb get-item ...)` inline — DDB `Items[]` with type-tagged `AttributeValue` maps are massively verbose for a usually-tiny lookup. Delegate to `dynamodb-inspector`.
- For WRITES (`put-item`/`update-item`/`delete-item`), use `dynamodb-mutator`, not this agent.

Note: `dynamodb-inspector` returns table + matched items + per-item key/value summary; verbatim AWS error code on failure. Read-only.
