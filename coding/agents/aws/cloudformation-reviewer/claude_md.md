### Task dispatch — CloudFormation template / change-set review → `cloudformation-reviewer` (Sonnet, read-only)

| Goal | Agent |
|---|---|
| "review this CloudFormation", "audit the CFN template", "is this stack safe to deploy", "check IAM in the template", "review the change set" | `cloudformation-reviewer` |

Anti-patterns:

- Reviewing a CloudFormation template (`.yaml`/`.yml`/`.json`/`.template`) or change-set output inline in the main session — large templates plus the structured security/cost/IAM assessment burn context. Delegate to `cloudformation-reviewer` and act on its severity-graded findings.
- Do NOT route DEPLOYS here — `create-stack`, `update-stack`, `deploy`, `execute-change-set` are state-changing and stay deliberately invoked (`cloudformation-deployer`), never auto-delegated.

Note: `cloudformation-reviewer` (Sonnet) reads templates / change sets and returns a structured, severity-graded assessment (security, cost, IAM scope, deprecated resource types, operational hazards). It never executes CloudFormation operations. Run it BEFORE create/update, especially in prod.
