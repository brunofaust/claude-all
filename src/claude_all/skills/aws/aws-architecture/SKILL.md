---
name: aws-architecture
description: >-
  Use when designing or reviewing AWS serverless architecture, service selection, reliability, scaling or IaC trade-offs. Execution belongs to deployer and inspector agents.
disable-model-invocation: false
user-invocable: true
---

# AWS Architecture Skill

Anchored to **AWS Well-Architected Framework** (Reliability, Performance, Cost, Operational Excellence, Security, Sustainability) + the **Serverless Application Lens**. Focus: serverless + event-driven workloads at production scale.

This skill encodes the "what to do" and the "why" — for execution of `terraform`/`aws` commands use the existing agents (`terraform-deployer`, `aws-lambda-deployer`, AWS read-only inspectors).

## Table of references

Deeper recipes live under `references/`. Read the matching file before deep work in that area:

| If you are…                                                                  | Read                                                                  |
| ----------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Making an async Lambda idempotent (Powertools recipe + JMESPath key matrix)  | [`references/idempotency.md`](references/idempotency.md)              |
| Choosing RDS vs DynamoDB per table, or planning a relational → DDB migration | [`references/rds-vs-dynamodb.md`](references/rds-vs-dynamodb.md)      |
| Organizing boto3/aiobotocore code (`core/aws/` owner-per-service layout)     | [`references/client-wrappers.md`](references/client-wrappers.md)      |
| Recording an architecture decision (ADR template + worked example)           | [`references/adr-template.md`](references/adr-template.md)            |

______________________________________________________________________

## 1. Lambda

### Memory + cold start

- Memory is also CPU. Lambda allocates CPU proportional to memory. **Run the AWS Lambda Power Tuner** before guessing. Sweet spots are usually 1024–1769 MB (vCPU = 1) or 3008+ MB (vCPU ≥ 2).
- Cold-start cost scales with:
    - Package size (250 MB unzipped hard limit, 50 MB ZIP direct upload; **use S3 for anything > 50 MB**)
    - Number of imported modules at top-level
    - VPC attachment — **avoid VPC unless necessary**. VPC attachment now uses Hyperplane ENIs (fast) but still adds cold-start tax. Lambdas needing only AWS APIs should run outside VPC.
    - SnapStart (Java / Python 3.12+ / .NET) reduces cold starts by 90%+. Use for latency-sensitive sync paths.

### Idempotency

Every async-invocable Lambda (SQS, SNS, EventBridge, S3) **must be idempotent**. AWS re-invokes on failure. Idempotency keys → DynamoDB conditional writes, or the AWS Lambda Powertools idempotency utility.

Concrete Powertools recipe (DynamoDB-backed persistence store) + the JMESPath decision matrix for picking the idempotency key per event shape → [`references/idempotency.md`](references/idempotency.md).

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
| Throughput | ~unlimited                            | 300 msg/s per queue without batching (3,000/s with batching); high-throughput mode raises the per-queue cap much higher (tens of thousands/s, region-dependent) — check current quotas |
| Use when   | High throughput, order doesn't matter | Ordered events per customer / aggregate                 |

### Visibility timeout

Rule: visibility timeout **≥ 6× processing time**. Too short = duplicate processing. Too long = slow DLQ on poison messages.

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

A *per-table* decision (most real systems use both). Full criteria (when DynamoDB / when RDS) + the relational → DynamoDB migration checklist → [`references/rds-vs-dynamodb.md`](references/rds-vs-dynamodb.md).
Rule of thumb: every access pattern known up front and key-based → DynamoDB; relational / variable / transactional → RDS (the safer default when unsure).

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

- Two Lambdas in sequence — chain via SQS or an async (`Event`) invoke; never a sync Lambda-from-Lambda call (see Lambda anti-patterns). Step Functions overhead isn't worth it for a 2-step flow.
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

## 10.5 AWS client wrappers — one owner per service

Contain every AWS SDK call behind a thin async wrapper, one file per service, in a settings-free `core/aws/` package.
Layout, session-reuse pattern, and the ownership rules → [`references/client-wrappers.md`](references/client-wrappers.md).

______________________________________________________________________

## 10.6 Multi-tenant resource isolation — ABAC / STS session tags

For a multi-tenant workload, scope cloud resources per tenant the way RLS scopes rows: **one** customer role, every grant conditioned on `${aws:PrincipalTag/org_id}`, and the worker assumes that role with a session tag rather than provisioning per-org roles. The worker assumes the tagged role **itself** from the tenant id in its own validated payload — never pass STS creds through orchestration payloads (role-chaining caps the session at 1h and puts tokens in transit). Mint STS lazily, cache credentials org-keyed with expiry refresh (AssumeRole is rate-limited — once per org per session, not per call), use the regional STS endpoint, and **FAIL-CLOSED** on a mint failure (never fall back to the platform role). A structural win: give the customer role no ai-model/Bedrock permissions, so "never bill the platform for a tenant's LLM call" is an IAM boundary, not a review checklist.

**Spike support per service — the matrix is learned, not documented.** Whether a session tag actually scopes a service is service-specific and often documented incorrectly: S3 prefix policies YES, per-org vector-index ARNs YES, DynamoDB `LeadingKeys` YES **only where the partition key leads with the tenant id**, catalog/table stores (Iceberg-style) often NO (session tags are engine trust lists, not row selectors — fall back to per-org filter+grant or a trusted query layer). Run a live spike per service before relying on it.

Full patterns, the YES/NO matrix, and the boundary-contract + billing-isolation rationale → [`../../python/brunofaust-python-style/references/tenant-isolation.md`](../../python/brunofaust-python-style/references/tenant-isolation.md) (§4).

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

Every non-trivial AWS design choice (DynamoDB vs RDS, SNS vs EventBridge, Lambda vs ECS, sync vs async, VPC vs no-VPC, …) must produce a one-page ADR checked into `docs/adr/`.
Template + worked example + the when-NOT-to-write list → [`references/adr-template.md`](references/adr-template.md).

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
