### `incident-responder` (Sonnet) — cross-service incident investigator
| "check this alarm", "DLQ growing", "investigate alert X", "what's wrong in prod / dev", "trace failure through pipeline", "got paged for" | `incident-responder` |
⛔ Opening an investigation with raw `aws sqs get-queue-attributes` + `aws logs tail` + `psql` chains — the agent picks the right sub-agents, correlates timestamps, and returns a unified VERBATIM-error timeline. Bypassing costs 5-10× more tokens.
Note: never makes destructive calls (DLQ redrive, message delete) without explicit user confirmation.
