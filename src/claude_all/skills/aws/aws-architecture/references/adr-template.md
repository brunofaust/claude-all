# Architecture Decision Records (ADRs)

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
myapp's events pipeline publishes "entity-updated" events that need to
reach: 3 internal consumers (Lambda), 1 external partner account (different
AWS org), and a future replay/audit consumer. Throughput: ~500 events/sec peak.

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
