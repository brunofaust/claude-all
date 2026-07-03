# Lambda idempotency — Powertools recipe + JMESPath key matrix

Concrete Powertools recipe (DynamoDB-backed persistence store):

```python
from aws_lambda_powertools.utilities.idempotency import (
    DynamoDBPersistenceLayer,
    idempotent,
    IdempotencyConfig,
)

persistence_layer = DynamoDBPersistenceLayer(
    table_name="idempotency-store",
)

config = IdempotencyConfig(
    event_key_jmespath="ticket_key",  # uniquely identifies the request
    expires_after_seconds=3600,  # 1h dedup window (also DDB TTL)
    raise_on_no_idempotency_key=True,  # fail loud on missing key
)


@idempotent(config=config, persistence_store=persistence_layer)
def handler(event, context):
    # business logic — guaranteed once-per-key within the TTL window
    ...
```

The idempotency table should have:

- PK `id` (string), `expiration` attribute as DynamoDB TTL → free auto-cleanup.
- On-demand billing (writes are spiky, one per invocation).

**JMESPath decision matrix** — which key uniquely identifies the request:

| Event shape                                          | JMESPath                                                 | Why                                                                 |
| ---------------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------- |
| API Gateway sync request with idempotency-key header | `headers."Idempotency-Key"`                              | Client-supplied, RFC-standard idempotency                           |
| SQS message with explicit business key               | `Records[0].body.<field>`                                | Use the business identifier (order_id, ticket_key)                  |
| EventBridge event                                    | `detail.<unique_field>`                                  | The domain event ID, not `id` (which is the bus event ID, fine too) |
| S3 ObjectCreated                                     | `Records[0].s3.object.key` + `Records[0].s3.object.eTag` | Key alone repeats on overwrite — pair with ETag                     |
| No natural key, full-event hash acceptable           | omit `event_key_jmespath`, set `use_local_cache=False`   | Powertools hashes the entire event                                  |
| Multiple fields jointly unique                       | `[customer_id, order_id]`                                | JMESPath returns a list; Powertools hashes it                       |

If `raise_on_no_idempotency_key=True` and the JMESPath returns `None`, the
Lambda fails — preferable to silently dedup nothing.
