### `terraform-reviewer` (Sonnet) — review `.tf` before it ships
**The diff is the trigger, not the phrasing.** If a change touches `.tf` files, dispatch this agent —
even when nobody said the word "terraform". "Ship this PR" over a diff containing infra files is an
IaC review you owe; the agent's own trigger phrases only fire when someone thinks to ask for one.
⛔ Reviewing `.tf` files or plan output inline in main session
⛔ Landing an IaC-touching diff on the strength of the generic code review alone
Note: read-only — never executes Terraform. Pairs with `terraform-deployer`: review first, then deploy.
