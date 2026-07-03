### `dynamodb-mutator` (Sonnet) — DynamoDB writes
| `aws dynamodb put-item/update-item/delete-item/batch-write-item/transact-write-items` | `dynamodb-mutator` (requires explicit "yes delete/write/update" confirmation) |
⛔ `Bash(aws dynamodb delete-item / put-item / update-item ...)` inline — even "innocent" resets (clearing run-locks, deleting step_progress to re-trigger a Lambda) are real mutations on real data.
⛔ Wrapping a destructive `aws dynamodb` call inside a `python3` heredoc to dodge the dispatch rule — delegate the OPERATION; the agent bakes in the confirmation gate AND a BEFORE-snapshot for rollback.
Note: for READS use `dynamodb-inspector`.
