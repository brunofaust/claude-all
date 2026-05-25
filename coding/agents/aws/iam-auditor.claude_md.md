### Command dispatch — IAM inspection → `iam-auditor` (Haiku)

| Command | Agent |
|---|---|
| `aws iam get-role / get-role-policy / get-policy / get-policy-version / simulate-principal-policy` | `iam-auditor` |

Anti-pattern:
- `Bash(aws iam get-role-policy ...)` / `Bash(aws iam get-policy-version ...)` / `Bash(aws iam simulate-principal-policy ...)` — delegate to `iam-auditor`. These return verbose policy JSON documents and simulation results; the agent surfaces findings with severity labels.

Note: simple list calls (`list-role-policies`, `list-attached-role-policies`) return short name lists and are fine in the main session when only the names are needed.
