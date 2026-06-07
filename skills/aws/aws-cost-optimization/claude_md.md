## AWS cost optimization — `aws-cost-optimization` skill
Apply when auditing AWS bill, hunting idle/orphaned resources, or choosing pricing model (On-Demand/Savings Plans/Reserved/Spot/Graviton).

Query AWS engines first: Cost Optimization Hub → Compute Optimizer → Trusted Advisor → Cost Explorer. Right-size before commitments. Key levers: Graviton (~20% price/perf), `gp2`→`gp3`, NAT→VPC endpoints, set CW log retention, delete stale snapshots/EIPs/old Lambda versions.
