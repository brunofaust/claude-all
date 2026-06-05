## AWS cost optimization — aws-cost-optimization skill

When auditing an AWS bill, hunting idle / over-provisioned / orphaned resources, or choosing a pricing model (On-Demand / Savings Plans / Reserved / Spot / Graviton), apply the `aws-cost-optimization` skill.

- **Query AWS's own engines FIRST** (don't hand-roll describe-loops): Cost Optimization Hub → Compute Optimizer (`get-idle-recommendations`) → Trusted Advisor → Cost Explorer → CUR/Athena.
- Right-size **before** buying commitments; commitments only for a stable baseline; Spot only for fault-tolerant work.
- Levers: Graviton (~20% price/perf), S3/EBS lifecycle (`gp2`→`gp3`), NAT → VPC endpoints, set CW log retention, delete stale snapshots/EIPs/old Lambda versions.

Pairs with the `cost-audit-runner` agent (resource-level waste hunt) and `cost-explorer` agent (spend totals/trends).
