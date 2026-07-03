# AWS client wrappers — one owner per service (`core/aws/`)

> One proven layout (from `brunofaust-python-style`); adapt names to the repo.

How you *organize the boto3 code* matters as much as the architecture. Contain every AWS SDK call
behind a thin async wrapper, one file per service, in a settings-free `core/aws/` package:

```
core/aws/
├── base.py        # shared AWSClient base + process-wide aiobotocore session reuse
├── s3.py          # S3Client(AWSClient)
├── sqs.py         # SQSClient(AWSClient)
├── dynamodb.py    # DynamoDBClient(AWSClient)
├── sns.py  ├ secrets.py  ├ sfn.py  ├ logs.py  └ …   # one file per service
```

Rules:

- **One file per service.** `core/aws/s3.py` is THE only place `aiobotocore`'s S3 client is created.
  Nothing else imports the SDK (enforce with ruff `banned-api` / TID251 — see the
  `brunofaust-python-style` external-system-ownership reference).
- **Share one session in `base.py`.** Lambda reuses the execution environment across invocations, so
  a process-wide `aiobotocore` session + per-service client cache avoids re-creating clients on every
  warm invoke (a real cold-vs-warm latency win):

  ```python
  # core/aws/base.py
  _session: AioSession | None = None
  clients: dict[str, Any] = {}          # service_name -> client, reused across invocations

  def get_session() -> AioSession:
      global _session
      if _session is None:
          _session = aio_get_session()
      return _session
  ```

- **Settings-free.** Region / table names / bucket names are passed in (constructor args or
  `Settings` injected by the caller), never imported inside `core/aws/`. That keeps the package
  extractable as a shared library across services.
- **`core/aws/` ≠ `aws_resources/`.** `core/aws/` holds the reusable *client wrappers*;
  `aws_resources/` holds the *deployable units* (Lambda handlers, ECS tasks) that consume them.
