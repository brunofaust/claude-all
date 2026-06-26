### `ecr-manager` (Haiku) — ECR repo inspection + prune
| `aws ecr describe-repositories / list-images`, "latest tag", "find / prune old images", "repo size" | `ecr-manager` |
⛔ `Bash(aws ecr describe-repositories ...)`, `Bash(aws ecr list-images ...)` inline
Note: read ops run freely; delete ops require explicit confirmation ("delete confirmed", "yes prune").
