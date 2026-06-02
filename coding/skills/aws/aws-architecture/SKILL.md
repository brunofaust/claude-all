---
name: aws-architecture
description: >-
  AWS serverless + event-driven architecture patterns. Use when: designing Lambda functions, picking between SQS/SNS/EventBridge, sizing DynamoDB capacity, designing Step Functions workflows, choosing API Gateway flavour, designing ECS / Fargate services, reviewing IaC (Terraform/CloudFormation) for AWS architectural fitness, debugging Lambda cold starts, sizing visibility timeouts, picking partition keys, designing DLQ + retry strategies, or reviewing AWS cost / performance trade-offs.
disable-model-invocation: false
user-invocable: true
---

# AWS Architecture Skill

Anchored to **AWS Well-Architected Framework** (Reliability, Performance, Cost, Operational Excellence, Security, Sustainability) + the **Serverless Application Lens**. Focus: serverless + event-driven workloads at production scale.

This skill encodes the "what to do" and the "why" — for execution of `terraform`/`aws` commands use the existing agents (`terraform-deployer`, `aws-lambda-deployer`, AWS read-only inspectors).

______________________________________________________________________

## 1. Lambda

### Memory + cold start

- Memory is also CPU. Lambda allocates CPU proportional to memory. **Run the AWS Lambda Power Tuner** before guessing. Sweet spots are usually 1024–1769 MB (vCPU = 1) or 3008+ MB (vCPU ≥ 2).
- Cold-start cost scales with:
    - Package size (250 MB unzipped hard limit, 50 MB ZIP direct upload; **use S3 for anything > 50 MB**)
    - Number of imported modules at top-level
    - VPC attachment — **avoid VPC unless necessary**. VPC attachment now uses Hyperplane ENIs (fast) but still adds cold-start tax. Lambdas needing only AWS APIs should run outside VPC.
    - SnapStart (Java / Python 3.13+ / .NET) reduces cold starts by 90%+. Use for latency-sensitive sync paths.

### Idempotency

Every async-invocable Lambda (SQS, SNS, EventBridge, S3) **must be idempotent**. AWS re-invokes on failure. Idempotency keys → DynamoDB conditional writes, or the AWS Lambda Powertools idempotency utility.

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

### Error handling per invocation type

| Invoke mode                           | Retry behaviour                                    | DLQ                                                                 |
| ------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------- |
| Sync (API GW, ALB)                    | Caller retries                                     | n/a                                                                 |
| Async (S3, SNS, EventBridge → Lambda) | 2 retries with exponential backoff                 | Configure `DeadLetterConfig` (SQS or SNS) — required for production |
| Poll (SQS, Kinesis, DynamoDB Streams) | Re-receive until visibility timeout × max receives | Configure redrive policy on the source queue                        |

### Concurrency

- **Reserved concurrency** — caps a function (protects downstream). Set when a function calls a small RDS Proxy or rate-limited API.
- **Provisioned concurrency** — pre-warmed. Costs money. Use only on sync user-facing paths with strict P95 budgets.
- Default account concurrency is 1000 per region. Request an increase before launch if any path can spike past it.

### Anti-patterns

- Calling another Lambda synchronously (`aws lambda invoke`) — double-pays for compute + couples lifecycles. Use Step Functions, EventBridge, or SQS instead.
- Long-running Lambdas (> 5 min) — 15-min cap; consider ECS Fargate or Step Functions.
- Lambda with VPC + no NAT/VPC endpoint for AWS APIs — silent hang on first SDK call.
- Mutating ENV vars at runtime — they're set at init, not per invocation.

______________________________________________________________________

## 2. SQS

### Standard vs FIFO

|            | Standard                              | FIFO                                                    |
| ---------- | ------------------------------------- | ------------------------------------------------------- |
| Order      | Best-effort                           | Strict, per `MessageGroupId`                            |
| Delivery   | At-least-once                         | Exactly-once (with dedup ID, 5-min window)              |
| Throughput | ~unlimited                            | 300 msg/s (3000/s with high-throughput mode, per-group) |
| Use when   | High throughput, order doesn't matter | Ordered events per customer / aggregate                 |

### Visibility timeout

Rule: **6× the average successful processing time**, OR Lambda timeout + buffer when SQS → Lambda. If Lambda has 30s timeout, queue visibility ≥ 60s. Too short = duplicate processing. Too long = slow DLQ on poison messages.

### DLQ + redrive

Always configure a DLQ. Set `maxReceiveCount` = 3–5. Build a dashboard alarm on `ApproximateNumberOfMessagesVisible` on the DLQ — silent DLQ accumulation hides real bugs.

### Message size

256 KB hard limit. For larger payloads use **SQS Extended Client** pattern: store body in S3, send only the S3 key in the message. The Extended Client library handles both ends.

### Batching

`aws lambda` SQS integration: batch size 1–10000, batch window 0–300s. For Lambda: prefer small batches (10) with short window (1–5s) unless throughput-critical. **Enable `ReportBatchItemFailures`** — partial-batch failure response lets you fail only the bad messages, not the entire batch.

### Anti-patterns

- Setting `maxReceiveCount = 1` — no retry buffer for transient failures.
- Forgetting `MessageGroupId` on FIFO — every message in one group serializes.
- Polling SQS with long-running consumer — use Lambda SQS event source (managed long-poll) or `WaitTimeSeconds=20`.

______________________________________________________________________

## 3. SNS

### Fanout pattern

SNS → multiple SQS subscribers is the canonical fanout. Each subscriber gets its own DLQ + processing rate. Use this over Lambda → multiple Lambda invokes.

### Filter policies

`SubscriptionFilterPolicy` on the SNS subscription filters at the SNS level — only matching messages flow to that SQS queue. **Free at the SNS side**, charged on SQS only for messages that pass. Big cost saver when many subscribers each want a slice.

### FIFO topics

Same FIFO guarantees as FIFO SQS, but only FIFO SQS can subscribe. Use only if you need ordered fanout (rare).

### Anti-patterns

- SNS → Lambda directly for production fanout — no DLQ at the SNS level (only Lambda async retries). Use SNS → SQS → Lambda for retry isolation.
- Cross-region SNS publish — possible but expensive + slow. Replicate via EventBridge cross-region routing instead.

______________________________________________________________________

## 4. EventBridge vs SNS vs SQS

Decision matrix:

| Need                                                         | Use                                                                                        |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| Pub/sub, multiple known subscribers                          | **SNS → SQS** (per subscriber)                                                             |
| Pub/sub with rich JSON filtering rules                       | **EventBridge** (default bus or custom bus)                                                |
| Producer wants to forget, one consumer, work queue semantics | **SQS** directly                                                                           |
| Schema versioning + replay                                   | **EventBridge** (archives + replay)                                                        |
| Cross-account routing                                        | **EventBridge** (rule-based, no policy gymnastics)                                         |
| Scheduled/cron triggers                                      | **EventBridge Scheduler** (replaces CloudWatch Events rules — better quotas, retries, DLQ) |
| Throughput > 10k events/s, simple routing                    | SNS (cheaper)                                                                              |
| Low volume, complex routing logic                            | EventBridge                                                                                |

EventBridge costs: $1.00/million for custom bus events, free for default bus + most AWS service events. SNS: $0.50/million publishes + delivery cost per protocol. For < 1M events/month either is cheap.

______________________________________________________________________

## 5. ECS

### Fargate vs EC2

|                     | Fargate                          | EC2                             |
| ------------------- | -------------------------------- | ------------------------------- |
| Ops burden          | None (serverless)                | You patch + autoscale ASG       |
| Cost (steady-state) | ~20–30% more than equivalent EC2 | Cheaper                         |
| Cost (bursty)       | Wins (no idle nodes)             | Loses (over-provisioned)        |
| GPU                 | No (use ECS GPU + EC2)           | Yes                             |
| Default choice      | Fargate                          | Only for steady fleet > 50 vCPU |

Use **Fargate Spot** for batch + retry-tolerant workloads — up to 70% cheaper.

### Service vs Task

- **Service**: long-running, autoscaled, ALB/NLB attached. Default for APIs and consumers.
- **Standalone task**: one-shot. Triggered by EventBridge Scheduler or Step Functions.

### Autoscaling

- Target tracking on `CPUUtilization` (default 50%) for general loads.
- For consumer services backed by SQS: target tracking on `ApproximateNumberOfMessagesVisible` per task — much more responsive than CPU.
- Always set `min_capacity ≥ 2` in prod for HA. Single-task services have downtime on every deploy.

______________________________________________________________________

## 6. DynamoDB

### Partition key design

The single most important decision. Bad PK = throttled hotspots that no amount of capacity fixes.

Rules:

- High-cardinality values (user_id, order_id), NOT timestamps or status enums.
- For time-series, **prefix with a high-cardinality value**: `org_id#YYYY-MM-DD` not `YYYY-MM-DD`.
- Sort keys give 1:N access patterns within a PK. Sparse SKs unlock common composite queries cheaply.

### Single-table vs multi-table

Single-table design (Alex DeBrie style) — fewer tables, generic PK/SK names, GSIs for inverted access. Wins for tightly-coupled domain models with many access patterns. Loses for independent domains (just use separate tables — no shame).

Don't single-table-design just because you read about it. **Three-or-fewer tables is fine for most apps.**

### RDS vs DynamoDB — decide per table, by access pattern

This is a *per-table* decision, not a whole-app one — most real systems use **both** (polyglot
persistence): DynamoDB for the connectionless/ephemeral tables, RDS/Aurora for the relational core.

**Use DynamoDB for the table when ANY of these hold:**

- **High Lambda (or other serverless) fan-out without RDS Proxy.** Each concurrent Lambda holds an
  RDS connection; without RDS Proxy you hit `max_connections` fast. DynamoDB is connectionless
  (HTTPS, IAM-auth) — no pool to exhaust. (With RDS Proxy you *can* fan out to RDS — so this point is
  conditional on not having/ wanting the proxy.)
- **Insert-only / append-only** — event logs, audit trails, time-series keyed by entity. No updates,
  no joins.
- **Needs TTL auto-expiry** — sessions, ephemeral state, caches. DynamoDB TTL deletes expired items
  for free (~48h async window); doing this in RDS means a reaper job.
- **Idempotency keys / distributed locks** — single-item atomic conditional writes
  (`attribute_not_exists`) are exactly DynamoDB's strength; pair with TTL to expire keys.
- **Access is by a known key** — get/put by partition key (± sort key), no ad-hoc `WHERE`.
- **Extreme or spiky write throughput, single-digit-ms point latency, or serverless scale-to-zero.**

**Use RDS / Aurora for the table when ANY of these hold:**

- **Joins** across entities.
- **Multi-row / multi-table ACID transactions** (DynamoDB `TransactWriteItems` caps at 100 items and
  has no cross-"table" relational semantics).
- **Ad-hoc queries, reporting, aggregations, analytics** where the query shape isn't known up front.
- **Rich relational integrity** — foreign keys, `CHECK`/uniqueness constraints, referential cascades.
- **Querying on many attributes** (DynamoDB needs a key/GSI designed per access pattern; max 20 GSIs).

Rule of thumb: if you can write down every access pattern up front and they're all key-based →
DynamoDB. If queries are relational/variable/transactional → RDS. When unsure, **RDS is the safer
default** (you can always add a DynamoDB table for the specific hot/ephemeral access pattern later).

### Relational → DynamoDB migration: when it's worth it

Moving an existing RDS/Postgres workload to DynamoDB is a big, often-irreversible bet. Decide on the
*access patterns*, not the hype. Run this checklist BEFORE migrating:

- **Enumerate every query first.** List all current SQL access patterns (point lookups, ranges,
  joins, aggregations, ad-hoc reporting). DynamoDB serves only patterns you designed a key/GSI for —
  there is no `JOIN`, no ad-hoc `WHERE`, no `GROUP BY`. If the app does multi-table joins or analysts
  run arbitrary queries, DDB is the wrong store (or needs a separate analytics path: S3 export +
  Athena).
- **What actually drives the move?** Good reasons: extreme write throughput, predictable
  single-digit-ms point lookups at scale, serverless scale-to-zero, or **RDS connection-limit /
  RDS-Proxy pain** under high Lambda fan-out (each Lambda holds a connection; DDB is connectionless).
  Bad reasons: "NoSQL is modern", "joins feel slow" (add an index first).
- **Cost compare honestly.** DDB on-demand at high steady throughput can cost *more* than a
  right-sized RDS instance. Model write/read units against real traffic; don't assume DDB is cheaper.
- **Relational integrity moves to the app.** No foreign keys, no transactions across "tables" beyond
  `TransactWriteItems` (25-item cap), no `CHECK` constraints. You own consistency now.
- **Migration is expand-contract, not big-bang.** Dual-write to both stores, backfill DDB from a
  Postgres snapshot, shadow-read and diff, then cut over. Keep Postgres as the rollback for a while.

Default verdict: if you can't write down every access pattern up front and they're all key-based,
**keep Postgres**. Migrate only when a specific scale/throughput/connection driver forces it.

### On-demand vs provisioned

- **On-demand**: pay per request. Default for unpredictable / spiky loads.
- **Provisioned**: cheaper at high steady throughput (> ~70% utilization sustained). Use with autoscaling.
- Adaptive capacity is automatic — hot partition isolation. Doesn't save you from a single hot partition key.

### GSIs

- **Sparse indexes** — items without the GSI attribute aren't indexed. Use this to make GSIs cheap (only "interesting" items index).
- GSI eventual consistency cannot be made strong. Don't read your own write through a GSI.
- Maximum 20 GSIs per table. Each costs storage + writes (replicated).

### TTL

Set TTL attribute (epoch seconds) on items you want auto-deleted. Free, async (~48h window). Great for ephemeral state, idempotency keys, session tokens.

### Anti-patterns

- `Scan` in hot paths. Always.
- Single hot partition (e.g. `status=active` as PK) — no amount of capacity fixes it.
- Storing > 400KB items — hard limit. Offload blob to S3, keep pointer in DDB.
- Eventually consistent read of own write within < 1s — use strongly-consistent read on the main table, never a GSI.

______________________________________________________________________

## 7. Step Functions

### Express vs Standard

|                               | Standard                            | Express                                                     |
| ----------------------------- | ----------------------------------- | ----------------------------------------------------------- |
| Duration                      | 1 year                              | 5 minutes                                                   |
| Pricing                       | Per state transition                | Per duration + memory                                       |
| Use when                      | Long-running workflows, audit trail | High-volume event processing (replace orchestrator Lambdas) |
| At-least-once or exactly-once | Exactly-once                        | At-least-once                                               |

Rule of thumb: if your workflow is < 5 min AND fires > 100k times/day, Express is dramatically cheaper. Otherwise Standard.

### Error handling

Build retries into the state machine, not the Lambdas:

- `Retry` with `IntervalSeconds`, `MaxAttempts`, `BackoffRate`
- `Catch` to a failure-handling branch
- Use **Step Functions intrinsic functions** instead of pass-through Lambdas (`States.ArrayContains`, `States.Format`, etc.) — free, no cold-start.

### When NOT to use Step Functions

- Two Lambdas in sequence — just call one from the other (or chain via SQS). Step Functions overhead isn't worth it.
- Synchronous user request paths — latency budget too tight.

______________________________________________________________________

## 8. API Gateway

### REST vs HTTP API

|          | REST                                                    | HTTP                                          |
| -------- | ------------------------------------------------------- | --------------------------------------------- |
| Cost     | $3.50/M                                                 | $1.00/M (70% cheaper)                         |
| Latency  | Higher                                                  | Lower                                         |
| Features | Request validation, API keys, usage plans, X-Ray native | JWT auth (Cognito or external), CORS built-in |
| Use when | You need WAF / usage plans / SOAP / private APIs        | Default for new APIs                          |

**Default to HTTP API** unless you need REST-only features.

### Throttling

Set per-stage or per-method throttling. Default is 10,000 RPS per region — request increase early if expecting traffic.

### Caching

Only REST APIs have built-in caching. For HTTP APIs: cache at CloudFront in front. CloudFront has free 1TB egress tier + cheaper bandwidth than direct API GW.

______________________________________________________________________

## 9. Cost gotchas (the items that surprise you on the bill)

1. **NAT Gateway** — $0.045/hour ($32/mo) per NAT + $0.045/GB processed. **VPC endpoints** (interface for AWS services, gateway for S3/DynamoDB) bypass NAT entirely. Use them for any high-traffic AWS API call.

    **VPC endpoint vs NAT Gateway decision table:**

    | Use case                       | NAT Gateway           | VPC Endpoint (Interface)   | VPC Endpoint (Gateway) |
    | ------------------------------ | --------------------- | -------------------------- | ---------------------- |
    | Lambda → S3                    | $0.045/hr + $0.045/GB | n/a                        | **Free** — use this    |
    | Lambda → DynamoDB              | $0.045/hr + $0.045/GB | n/a                        | **Free** — use this    |
    | Lambda → Secrets Manager       | $0.045/hr + $0.045/GB | $0.01/hr per AZ + $0.01/GB | n/a                    |
    | Lambda → Lambda (cross-region) | $0.045/hr + $0.045/GB | $0.01/hr per AZ + $0.01/GB | n/a                    |
    | Lambda → public internet       | NAT GW required       | n/a                        | n/a                    |
    | Lambda outside VPC             | nothing               | not applicable             | not applicable         |

    **Rule:** Default to Lambda OUTSIDE the VPC. If it MUST be in a VPC (e.g.
    talking to RDS in a private subnet), add S3 + DynamoDB Gateway endpoints
    (free) plus Interface endpoints for any high-traffic AWS service (Secrets
    Manager, KMS, SQS, SNS) — cheaper than NAT once traffic > ~10 GB/month.

1. **CloudWatch Logs ingest** — $0.50/GB. Verbose Lambda logs (every event JSON dump) add up. Set `LOG_LEVEL=INFO` minimum in prod; ship debug to S3 if needed for retention.

1. **CloudWatch Logs storage** — $0.03/GB-month. Set log group retention; default is "Never expire".

1. **Lambda < 100ms** — billed in 1ms increments since 2020. Still, cold-start + init is a fixed cost. Don't optimize sub-ms; optimize architectural call patterns.

1. **DynamoDB Scan** — full table read. Always. Even with FilterExpression, you pay for every scanned item.

1. **Cross-AZ data transfer** — $0.01/GB each way. RDS Multi-AZ replication is free, but your app talking to a Multi-AZ DB across AZs is not.

1. **S3 LIST** — $0.005 per 1k. Fine until you list 100M-object buckets in a Lambda loop.

1. **Provisioned concurrency** — billed even when idle. Only on user-facing sync paths.

______________________________________________________________________

## 10. Security baseline

- Lambda execution role: **least privilege** per function. Avoid sharing one big role across many functions.
- KMS: encrypt Lambda env vars (`KmsKeyArn`) for any sensitive value. Test cold-start KMS Decrypt permissions early — they're a common silent prod failure.
- Secrets Manager > Lambda env vars for rotating credentials. Use Powertools `parameters` for caching.
- SQS / SNS / DDB: server-side encryption (SSE-KMS) for anything customer-related.
- IAM roles for service accounts (IRSA in EKS / Task roles in ECS) — never bake credentials in containers.

______________________________________________________________________

## 10.5 AWS client wrappers — one owner per service (`core/aws/`)

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

______________________________________________________________________

## Decision tree — "what should I use?"

```
Need to process events?
├── Event volume + N consumers known: SNS → SQS → Lambda
├── Event filtering / replay / cross-account: EventBridge
├── Single consumer, work queue: SQS → Lambda
└── Scheduled: EventBridge Scheduler

Need long-running compute?
├── < 15 min, stateless: Lambda
├── 5 min – hours, container: ECS Fargate task (one-shot)
├── Steady service: ECS Fargate service
└── Workflow with retries / branches: Step Functions

Need a database?
├── Key-value or known access patterns: DynamoDB
├── Relational + joins: RDS / Aurora Serverless v2
├── Time-series at huge volume: Timestream
└── Search / analytics: OpenSearch / Athena over Parquet

Need an API?
└── HTTP API + JWT auth (default). REST only if you need its features.
```

______________________________________________________________________

## 11. Architecture Decision Records (ADRs)

Every non-trivial AWS design choice (DynamoDB vs RDS, SNS vs EventBridge,
single-table vs multi-table, HTTP API vs REST API, Lambda vs ECS, sync vs
async invocation, VPC vs no-VPC, ECR vs ZIP deployment) must produce an ADR
checked into `docs/adr/` (or wherever the project keeps them).

ADRs are short — one page, max. They exist to answer the question "why is it
this way?" 6 months later when no one remembers the trade-off.

### Template

```markdown
# ADR-NNN: <short imperative title>

## Status

Proposed | Accepted | Deprecated | Superseded by ADR-XXX

## Context

What forced this decision? One paragraph. Include the constraints: scale,
latency targets, cost budget, team skill, existing infrastructure, compliance.

## Decision

The choice, stated as a sentence. "We will use X."

## Consequences

### Positive

- ...
- ...

### Negative

- ...
- ...

### Alternatives considered

- **Option B**: why it was rejected (one line)
- **Option C**: why it was rejected (one line)

## Date

YYYY-MM-DD
```

### Example — picking between SNS and EventBridge

```markdown
# ADR-007: Use EventBridge for cross-account domain events

## Status
Accepted

## Context
Datalake silver layer publishes "entity-updated" events that need to reach:
3 internal consumers (Lambda), 1 external partner account (different AWS
org), and a future replay/audit consumer. Throughput: ~500 events/sec peak.

## Decision
Use EventBridge custom bus with cross-account rules + S3 archive for replay.

## Consequences

### Positive
- Filter rules per consumer (SNS would broadcast everything)
- Cross-account fanout without IAM gymnastics on the publisher side
- Built-in archive + replay (90-day window) — no separate S3 archive pipeline
- Schema registry integration when we add CloudEvents

### Negative
- ~5x cost vs SNS at this volume ($1/M vs $0.50/M, plus archive storage)
- 256 KB event size limit (we're at 8 KB avg, fine for now)
- Slightly higher latency (~150 ms p99 vs SNS ~50 ms p99) — acceptable for
  async domain events

### Alternatives considered
- **SNS fanout**: cheaper, lower latency, but no filtering = consumer Lambda
  cold-start cost on every event regardless of relevance
- **Kinesis Data Streams**: overkill for 500 evt/s, shard management overhead
- **SQS direct per consumer**: publisher would need to know every consumer
  (tight coupling)

## Date
2026-04-15
```

### When NOT to write an ADR

- Naming choices (use the project naming convention)
- Library version bumps that don't change architecture
- Choices that are obviously determined by an existing constraint ("we use
    DynamoDB because we already use DynamoDB everywhere")
- Choices reversible in < 1 day

ADRs are for **load-bearing** decisions that someone in 6 months will want to
understand and might second-guess.

______________________________________________________________________

## References

- [AWS Well-Architected Framework](https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html)
- [Serverless Application Lens](https://docs.aws.amazon.com/wellarchitected/latest/serverless-applications-lens/welcome.html)
- [AWS Prescriptive Guidance patterns](https://aws.amazon.com/prescriptive-guidance/)
- [The DynamoDB Book](https://www.dynamodbbook.com/) (DeBrie) — single-table design
- [AWS Lambda Powertools](https://docs.powertools.aws.dev/) — idempotency, parameters, logging
- [AWS Pricing Calculator](https://calculator.aws/) — always model cost before commit
- [Planning where to use RDS Proxy](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy-planning.html) — connection-limit driver for the RDS-vs-DynamoDB decision
- [RDS Proxy connection considerations](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy-connections.html) — MaxConnectionsPercent / IdleClientTimeout tuning
- [DynamoDB Time to Live (TTL)](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html) — auto-expiry for ephemeral / idempotency tables
