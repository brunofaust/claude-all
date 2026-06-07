## AWS dev debug loop — `aws-debug-loop` skill
Apply when debugging e2e/integration test failures against a dev AWS environment (Lambda/Step Functions/SQS/DynamoDB/ECS multi-step pipelines).

Key rules: split failing tests into isolated pieces; hotfix dev environment directly (env vars, timeouts) to validate before full redeploy; run independent pieces in parallel; stop only when the full test passes clean.
