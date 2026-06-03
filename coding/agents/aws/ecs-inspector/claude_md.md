### Command dispatch — ECS inspection → `ecs-inspector` (Haiku)

| Command | Agent |
|---|---|
| `aws ecs describe-task-definition / describe-service / describe-tasks` | `ecs-inspector` |

Anti-pattern:
- `Bash(aws ecs describe-task-definition ...)` / `Bash(aws ecs describe-service ...)` / `Bash(aws ecs describe-tasks ...)` — delegate to `ecs-inspector`. Task definitions and service descriptions are large JSON with container definitions, env vars, and IAM role ARNs; the agent summarizes and redacts values.
