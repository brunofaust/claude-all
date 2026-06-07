### `sqs-monitor` (Haiku) — SQS queue inspection
| `aws sqs list-queues/get-queue-attributes/get-queue-url`, DLQ peek (`receive-message --visibility-timeout 0`) | `sqs-monitor` |
⛔ `Bash(aws sqs get-queue-attributes ...)`, `Bash(aws sqs receive-message ...)` inline
Note: DLQ redrive (`start-message-move-task`) requires explicit confirmation ("yes redrive").
