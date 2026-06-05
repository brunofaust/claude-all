## AWS dev debug loop — aws-debug-loop skill

When debugging e2e / integration test failures against an AWS **dev** environment (Lambda / Step Functions / SQS / DynamoDB / ECS, multi-step pipelines), apply the `aws-debug-loop` skill.

- Split a failing full test into isolated pieces; reproduce each in isolation before guessing.
- Hotfix the dev environment directly (env vars, timeouts, image versions) to validate a fix **before** doing a full redeploy.
- Run independent pieces in parallel; know when to declare a piece fixed vs. when to redeploy.
- **Stop condition:** the full test passes clean — never stop earlier.

For cross-service production incidents, use the `incident-responder` agent instead.
