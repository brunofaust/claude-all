## Auditing an existing / brownfield Python repo — repo-audit skill

When onboarding a colleague or inheriting an existing Python product, the FIRST pass is the
`repo-audit` skill — a whole-repo congruence audit against `brunofaust-python-style` and its gate
stack (ruff, mypy strict, import-linter, banned-api, interrogate, vulture, bandit, gitleaks,
`skill_enforcer`), plus Infrastructure-as-Code (CloudFormation + Terraform via cfn-lint / tflint /
checkov / tfsec) and a process-tooling pass (`session-harvest` → missing skills/agents/hooks). It
emits a per-dimension **scorecard** + a **ratcheting remediation roadmap**.

- **Brownfield rule: measure → baseline → ratchet, never big-bang.** Don't `--strict` everything or
  reformat the whole repo — that blocks every commit on legacy noise and hides regressions. Wire gates
  advisory, baseline caps at current-worst + margin, ratchet down one notch per PR. (→ `prek` skill.)
- **Report-only.** The audit measures and plans; it never fixes. Fixes are later *reviewed* PRs —
  `lint-fixer` (lint/type/complexity), `python-module-migrator` (layering), `test-author` (coverage).
- Use it for: first-time adoption of the standard, triaging what to fix first, quarterly health
  checks (trend vs last baseline). For a single diff use `verification-loop`; for security-only use
  `security-audit` (repo-audit delegates dimension 12 to it). IaC → `cloudformation-reviewer` /
  `iam-auditor` / `aws-architecture` (dim 13); process tooling → `session-harvest` (dim 14).
- **Per-project recommendations (dim 15):** repo-audit also profiles the project (stack / frameworks
  / cloud / DB) and recommends which claude-all agents/skills/hooks to install for THAT repo, plus
  net-new project-specific ones. Re-run it in each project for tailored suggestions.
- Gate every *structural* roadmap step through `architecture-decision-guard` (containment > layering).
