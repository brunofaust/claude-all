## Auditing an existing / brownfield repo (any language) — repo-audit skill

When onboarding a colleague or inheriting an existing product in **any language** (Python, TypeScript
/ frontend, Go, Rust, …), the FIRST pass is the `repo-audit` skill — a whole-repo congruence audit
against a set of **generic quality boundaries**: format/lint, static type safety, bounded complexity,
layering & dependency direction, single-owner external systems, typed contracts at trust edges, no
silent error swallowing, docs, dead code, tests/coverage, config discipline, secrets/SAST, plus IaC
(CloudFormation + Terraform) and a process-tooling pass (`session-harvest`). It emits a per-dimension
**scorecard** + a **ratcheting remediation roadmap**.

- **The boundaries are generic; the stack tooling varies.** `brunofaust-python-style` + `prek` are the
  *reference instantiation* (ruff / mypy / import-linter / banned-api / interrogate / vulture / bandit
  / gitleaks). For other stacks, translate each boundary to that stack's tools (eslint/tsc,
  golangci-lint, clippy, …); where no tool exists, audit by reasoning + `grep` — never skip a boundary.
  Frontend lenses → `react-correctness` / `react-testing` / `composition-patterns` /
  `web-design-guidelines` / `web-security` / `seo`.
- **Brownfield rule: measure → baseline → ratchet, never big-bang.** Don't `--strict` everything or
  reformat the whole repo — that blocks every commit on legacy noise and hides regressions. Wire gates
  advisory, baseline caps at current-worst + margin, ratchet down one notch per PR. (→ `prek` skill.)
- **Report-only.** It measures and plans; fixes are later *reviewed* PRs — `lint-fixer`,
  `python-module-migrator` (layering), `test-author` (coverage).
- For a single diff use `verification-loop`; for security-only use `security-audit` (repo-audit
  delegates dimension 12 to it). IaC → `cloudformation-reviewer` / `iam-auditor` / `aws-architecture`
  (dim 13); process tooling → `session-harvest` (dim 14, run once — no double-run).
- **Per-project recommendations (dim 15):** repo-audit profiles the project (stack / frameworks /
  cloud / DB) and recommends which claude-all agents/skills/hooks to install for THAT repo, plus
  net-new project-specific ones. Re-run it in each project for tailored suggestions.
- Gate every *structural* roadmap step through `architecture-decision-guard` (containment > layering).
