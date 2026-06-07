## AWS architecture — `aws-architecture` skill
Apply when designing/reviewing AWS workloads (Lambda, SQS/SNS/EventBridge, DynamoDB, ECS, Step Functions, API Gateway, Terraform/CloudFormation). Apply BEFORE writing IaC for new AWS resources.

Key quick checks: Lambda idempotency + 256 MB ZIP limit; SQS visibility timeout ≥ 6× processing time + DLQ; SNS for high-throughput fanout vs EventBridge for filtering/replay; DynamoDB high-cardinality keys, no scan in hot paths; HTTP API over REST API (70% cheaper); NAT Gateway → VPC endpoints.
