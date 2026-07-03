## AWS architecture — `aws-architecture` skill
Key quick checks: Lambda idempotency + package limits (50 MB zipped direct upload / 250 MB unzipped); SQS visibility timeout ≥ 6× processing time + DLQ; SNS for high-throughput fanout vs EventBridge for filtering/replay; DynamoDB high-cardinality keys, no scan in hot paths; HTTP API over REST API (70% cheaper); NAT Gateway → VPC endpoints.
