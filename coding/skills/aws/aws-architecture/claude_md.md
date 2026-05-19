## AWS architecture — aws-architecture skill

When designing or reviewing AWS workloads — Lambda functions, SQS / SNS / EventBridge routing, DynamoDB schema, ECS / Fargate services, Step Functions, API Gateway, Terraform / CloudFormation for AWS — apply the `aws-architecture` skill.

Quick references:
- **Lambda**: idempotency required for any async invoke; 256 MB ZIP / 50 MB direct upload limit (S3 above that); avoid VPC unless needed.
- **SQS**: visibility timeout ≥ 6× processing time, always configure DLQ + `ReportBatchItemFailures`.
- **SNS vs EventBridge**: SNS for high-throughput fanout, EventBridge for filtering / replay / cross-account / scheduling.
- **DynamoDB**: high-cardinality partition keys, never scan in hot paths, single-table only when access patterns justify it.
- **API Gateway**: HTTP API by default (70% cheaper than REST).
- **Cost gotchas**: NAT Gateway $/GB → use VPC endpoints; CW Logs ingest at $0.50/GB; cross-AZ at $0.01/GB.

Apply the skill BEFORE writing IaC for new AWS resources.
