### Command dispatch — Step Functions traces → `step-functions-tracer` (Haiku)

| Command | Agent |
|---|---|
| `aws stepfunctions describe-execution/get-execution-history/list-executions/describe-state-machine` | `step-functions-tracer` |

Anti-patterns:

- `Bash(aws stepfunctions get-execution-history ...)` inline — execution history is N events × verbose JSON + stack traces in `cause` fields, easily thousands of lines per failed run. Delegate to `step-functions-tracer`.
- A `… && sleep N && aws stepfunctions describe-execution …` wait loop — use the `wait-for-ready` skill (or the agent's poll) instead of a fixed `sleep`.

Note: `step-functions-tracer` returns the failed state + `cause` (verbatim) + execution timeline, not the raw event dump. Read-only.
