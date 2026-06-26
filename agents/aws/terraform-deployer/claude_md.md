### `terraform-deployer` (Haiku) — Terraform executor
| `terraform init/fmt/validate/plan/apply/destroy/state`, Makefile wrappers (`make tf-*`) | `terraform-deployer` |
⛔ `Bash(make tf-plan)`, `Bash(make terraform-init)`, `Bash(terraform apply ...)` inline
Note: shows the plan before apply; never `apply`/`destroy` without explicit confirmation. Cheap reads (`terraform output`, `state list/show`) also go through it.
