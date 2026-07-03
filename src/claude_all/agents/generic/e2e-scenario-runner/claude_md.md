### `e2e-scenario-runner` (Haiku) — multi-service end-to-end probe
| Set state → trigger → verify across DDB + Postgres + SQS + CloudWatch + Step Fn; "run e2e", "smoke test the flow", any 3+ sequential setup→trigger→verify steps | `e2e-scenario-runner` |
⛔ `Bash(aws lambda invoke ...)` + `Bash(aws logs ...)` + `Bash(aws sqs ...)` + `Bash(psql ...)` in the same turn — delegate the WHOLE probe; it captures verbatim evidence per step and stops on the first BLOCK.
⛔ Iterative "fix → reset DB → re-trigger Lambda → check → repeat" loops in main session — declare the scenario UPFRONT (setup, trigger, verifications, success criteria) and dispatch ONCE per iteration; Opus only decides the FIX between iterations.
