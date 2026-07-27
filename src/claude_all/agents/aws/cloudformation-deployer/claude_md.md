### `cloudformation-deployer` (Haiku) — CloudFormation stack operations
⛔ `Bash(aws cloudformation create-stack ...)`, `Bash(aws cloudformation update-stack ...)`,
`Bash(aws cloudformation deploy ...)` inline — even a single-stack update, even "just checking" with
`describe-stacks`. DELEGATE.
⛔ Deploying a template that has not been through `cloudformation-reviewer` — review first, then deploy.
Note: always creates a change set before create/update and shows it for confirmation; never runs
`delete-stack` or a destructive update without explicit confirmation.
