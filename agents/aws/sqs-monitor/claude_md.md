### Command dispatch — SQS queue inspection → `sqs-monitor` (Haiku)

| Command | Agent |
|---|---|
| `aws sqs list-queues/get-queue-attributes/get-queue-url`, DLQ peek (`receive-message --visibility-timeout 0`) | `sqs-monitor` |

Anti-patterns:

- `Bash(aws sqs get-queue-attributes ...)` / `Bash(aws sqs receive-message ...)` inline — SQS JSON includes base64-encoded message bodies + verbose attribute maps. Delegate to `sqs-monitor` for a tight depth / in-flight / DLQ summary.

Note: `sqs-monitor` returns per-queue depth + in-flight + DLQ depth + oldest-message age. DLQ redrive (`start-message-move-task`) is a WRITE — it requires explicit confirmation and is not auto-delegated as a read.
