### Command dispatch — AWS waste hunt → `cost-audit-runner` (Sonnet, read-only)

| Goal | Agent |
|---|---|
| "find AWS waste", "where's the money going", "idle/orphaned resources", "cost cleanup sweep" | `cost-audit-runner` |
| Spend totals / trends / forecast / cost-by-tag (Cost Explorer API) | `cost-explorer` |

Anti-patterns:
- Chaining `Bash(aws lambda list-versions-by-function …)` + `Bash(aws ec2 describe-addresses …)` +
  `Bash(aws logs describe-log-groups …)` + `Bash(aws rds describe-db-instances …)` in the main session
  to hunt for waste — that's a multi-service read-only sweep; delegate to `cost-audit-runner`, which
  fans out the probes and returns a prioritized findings report with non-executed `fix_commands`.
- Using `cost-explorer` for resource-level waste — it only answers "how much" (CE API totals/trends),
  not "which specific resource is idle and removable". Use `cost-audit-runner` for the latter.

`cost-audit-runner` is STRICTLY READ-ONLY: it never deletes/modifies, never `get-secret-value`, and
never executes the fix_commands it emits. Actually deleting a flagged resource is a separate step —
main session with explicit per-resource confirmation via the right deployer agent (e.g.
`aws-lambda-deployer` for Lambda versions).
