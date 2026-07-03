# RDS vs DynamoDB — per-table decision + migration checklist

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
  `TransactWriteItems` (100-item cap), no `CHECK` constraints. You own consistency now.
- **Migration is expand-contract, not big-bang.** Dual-write to both stores, backfill DDB from a
  Postgres snapshot, shadow-read and diff, then cut over. Keep Postgres as the rollback for a while.

Default verdict: if you can't write down every access pattern up front and they're all key-based,
**keep Postgres**. Migrate only when a specific scale/throughput/connection driver forces it.
