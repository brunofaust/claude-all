### `aws-lambda-deployer` (Haiku) — Lambda deploy / invoke / inspect
| `aws lambda update-function-code / invoke / list-functions / get-function-configuration`, Lambda-flavoured `make` targets | `aws-lambda-deployer` |
⛔ `Bash(aws lambda update-function-code ...)`, `Bash(aws lambda invoke ...)` inline — even a single-Lambda deploy, even "just checking" with invoke. DELEGATE.
⛔ Bypassing the agent on its first auth / SSO failure — fix the precondition (`aws sso login`), then RE-INVOKE the agent; never run the raw CLI in main session.
