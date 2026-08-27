---
name: aws-cost-optimization
description: >-
  Use when auditing AWS spend or waste, rightsizing resources, choosing commitments, reducing storage/network costs or setting cost controls.
disable-model-invocation: false
user-invocable: true
---

# AWS Cost Optimization

Grounded in the AWS Well-Architected **Cost Optimization pillar** and AWS's native recommendation
services. The #1 mistake is hand-rolling `describe`/`list` loops + CloudWatch math to find waste when
**AWS already computes it for you** — start with the engines below.

## Use AWS's recommendation engines FIRST (in this order)

1. **Cost Optimization Hub** — the aggregator. One ranked list of all recommendations across services
   with estimated monthly savings, de-duplicated.
   `aws cost-optimization-hub list-recommendations` / `list-enrollment-statuses`.
2. **Compute Optimizer** — idle + rightsizing, refreshed daily, with concrete criteria.
   - `aws compute-optimizer get-idle-recommendations` (EC2, ASG, EBS, ECS-on-Fargate, Aurora/RDS, NAT)
   - `get-ec2-instance-recommendations`, `get-auto-scaling-group-recommendations`,
     `get-ebs-volume-recommendations`, `get-lambda-function-recommendations`,
     `get-ecs-service-recommendations`, `get-rds-database-recommendations`
   - Idle criteria (default 14-day lookback): **EC2** peak CPU <5% & net I/O <5 MB/day; **EBS** <1
     op/day or unattached 32 days; **Fargate** peak CPU & mem <1%; **RDS/Aurora** no connections + low
     CPU + low IOPS (and not a read replica / global-secondary).
3. **Trusted Advisor** — ~40 cost checks (needs Business/Enterprise Support).
   `aws support describe-trusted-advisor-checks --language en` +
   `describe-trusted-advisor-check-result --check-id <id>`.
4. **Cost Explorer** — spend + commitment recommendations (CE API charges **$0.01/request** — use it
   judiciously). `ce get-cost-and-usage`, `get-savings-plans-purchase-recommendation`,
   `get-reservation-purchase-recommendation`, `get-anomalies`. Delegate to the `cost-explorer` agent.
5. **CUR + Athena** — deepest custom analysis (Cost & Usage Report in S3, queried via Athena) when the
   managed engines don't slice the way you need.

Only after these do you fall back to per-service `describe`/`list` probes for gaps they miss.

## Well-Architected Cost pillar — 5 areas

1. **Cloud financial management** — ownership, FinOps culture, tagging/allocation, showback/chargeback.
2. **Expenditure & usage awareness** — Cost Explorer, Budgets + alerts, Cost Anomaly Detection, CUR.
3. **Cost-effective resources** — right-size; right pricing model (On-Demand / SP / RI / Spot);
   managed services over self-managed where cheaper.
4. **Manage demand & supply** — autoscaling, scheduled scale-to-zero for non-prod, queue-based smoothing.
5. **Optimize over time** — review new instance families/services; re-rightsize as load changes.

## Waste catalog (what Trusted Advisor / Compute Optimizer flag)

| Category | Signal | Action |
|---|---|---|
| Idle compute | EC2/ASG/Fargate/RDS below idle thresholds | stop (non-prod) or delete; snapshot RDS/EBS first |
| Orphaned storage | unattached EBS, old manual snapshots, idle/unused volumes | snapshot → delete |
| Idle networking | unassociated Elastic IPs, idle NAT gateways, idle/cross-zone load balancers, inactive VPC interface endpoints | release / delete |
| Missing lifecycle | S3 buckets (esp. version-enabled) + ECR repos with no lifecycle policy; incomplete multipart uploads | add lifecycle / abort-incomplete rule |
| Over-provisioned | EC2/EBS/RDS/Redshift larger than utilization; Lambda over-allocated memory | right-size to recommendation |
| Lambda waste | excessive timeouts, high error rates (retry cost), over-provisioned memory | tune timeout/memory (Power Tuning) |
| Old Lambda versions | superseded published versions accruing storage | delete non-alias, non-$LATEST versions |
| Commitment gaps | steady usage on On-Demand; expiring RIs; under-utilized SP/RI | buy SP/RI for the stable baseline |
| Logs | CloudWatch log groups with no retention (never expire) or never read | set retention (e.g. 30d) |

## Optimization levers (playbook)

- **Right-size before you commit.** Never buy Savings Plans / RIs on top of over-provisioned
  resources — shrink first, then commit to the new baseline.
- **Pricing model by workload shape:** On-Demand = spiky/unknown; **Savings Plans / RIs** = stable
  baseline (1- or 3-yr, ≥~70% steady utilization); **Spot** = fault-tolerant/interruptible (batch,
  CI, async workers) — never stateful singletons.
- **Graviton (arm64)** — ~20% better price/performance for most Lambda/ECS/RDS/EC2 workloads; cheap
  win if the runtime supports arm64.
- **Storage tiering** — S3 Intelligent-Tiering or lifecycle to IA/Glacier; EBS `gp2`→`gp3` (cheaper +
  tunable); delete stale snapshots; S3 lifecycle to abort incomplete multipart uploads.
- **Serverless tuning** — size Lambda memory by Compute Optimizer / Lambda Power Tuning (more memory
  can be *cheaper* if it cuts duration); ARM; avoid idle provisioned concurrency.
- **Networking** — replace NAT-gateway data-processing with **VPC gateway/interface endpoints** for
  S3/DynamoDB/AWS APIs; keep traffic in-AZ to dodge cross-AZ $/GB; CloudFront for egress-heavy.
- **Demand shaping** — scheduled stop/scale-to-zero for dev/test off-hours (e.g. via EventBridge +
  Lambda, or Instance Scheduler); autoscaling on prod.

## Guardrails (FinOps hygiene)

- Right-size proactively; don't wait for a bill spike.
- Commitments only on demonstrably stable workloads — a 3-yr RI on a workload you'll re-architect is
  a loss.
- Test before migrating instance family / Graviton / storage class.
- Automate dev/test cleanup (TTL tags + a scheduled reaper).
- Tag everything for allocation; you can't optimize what you can't attribute.

## Shift cost left (CI / IaC)

- **Infracost** — Terraform/OpenTofu cost diff posted as a PR comment; catch a $/mo regression before
  merge.
- **Cloud Custodian** — policy-as-code governance (e.g. auto-stop untagged non-prod EC2, delete
  unattached EBS after N days). Treat as enforcement after the audit identifies the waste.
- **AWS Budgets + Cost Anomaly Detection** — alert on overspend / unexpected spikes; wire to SNS.

## FOCUS

The **FinOps Open Cost & Usage Specification (FOCUS)** is the vendor-neutral schema for normalizing
cost data across clouds — use it if you report cost across AWS + others.

## Anti-patterns

| Anti-pattern | Why | Use instead |
|---|---|---|
| Hand-rolled describe-loops + CW math to find idle | AWS already computes it daily | Compute Optimizer `get-idle-recommendations` / Cost Optimization Hub |
| Polling `ce get-cost-and-usage` in a loop | $0.01/request adds up | cache; query once at the right granularity; delegate to `cost-explorer` |
| Buying RIs/SPs before right-sizing | Locks in the over-provisioned size | right-size, then commit to the new baseline |
| Spot for stateful singletons | Interruption loses state | Spot only for fault-tolerant/interruptible work |
| Deleting flagged resources automatically | Idle ≠ unneeded (warm standby, DR) | surface as recommendations; delete with explicit human confirmation |
| 3-yr commitment on a workload you'll re-architect | Sunk cost | shorter term or On-Demand until the architecture settles |

## Related

- **`cost-audit-runner` agent** — runs the resource-level waste hunt (engines-first) read-only.
- **`cost-explorer` agent** — spend totals / trends / forecast / by-tag (CE API).
- **`aws-architecture` skill** — the cost gotchas baked into design (NAT, CW Logs ingest, cross-AZ).

## References (track these for updates)

AWS official:

- [Well-Architected — Cost Optimization pillar](https://docs.aws.amazon.com/wellarchitected/latest/framework/cost-optimization.html)
- [Compute Optimizer — viewing idle resource recommendations](https://docs.aws.amazon.com/compute-optimizer/latest/ug/view-idle-recommendations.html) (idle criteria per resource)
- [Trusted Advisor — cost optimization checks](https://docs.aws.amazon.com/awssupport/latest/user/cost-optimization-checks.html) (the ~40-check catalog)
- [Cost Optimization Hub — `list_recommendations`](https://docs.aws.amazon.com/boto3/latest/reference/services/cost-optimization-hub/client/list_recommendations.html)
- [FOCUS — FinOps Open Cost & Usage Specification](https://focus.finops.org/)

Open-source / ecosystem (prior art + tools worth referencing):

- [OptimNow/cloud-finops-skills](https://github.com/OptimNow/cloud-finops-skills) — FOCUS-aligned FinOps knowledge skill + MCP
- [zxkane/aws-skills](https://github.com/zxkane/aws-skills) — `aws-cost-operations` Claude Code skill
- [ahmedasmar/devops-claude-skills](https://github.com/ahmedasmar/devops-claude-skills) — `aws-cost-finops` skill
- [Cloud Custodian](https://github.com/cloud-custodian/cloud-custodian) — policy-as-code governance / auto-remediation
- [Infracost](https://github.com/infracost/infracost) — PR-time Terraform cost diffs
- [Komiser](https://github.com/tailwarden/komiser) — idle-resource inventory
