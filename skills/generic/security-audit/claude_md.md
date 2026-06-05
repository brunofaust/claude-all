## Security audit — security-audit skill

When doing a security pass before a release, threat-modeling a feature, auditing dependencies for CVEs, hardening CI/CD, securing an LLM-integrated feature, or sweeping for leaked secrets, apply the `security-audit` skill.

- Six layers: **app** (OWASP Top 10 — authz on every server endpoint, validate every input, rate-limit), **secrets** (scan full git *history*, not just HEAD), **dependency supply chain** (SBOM + osv-scanner/pip-audit/npm audit; pin lockfiles), **CI/CD** (pin actions to SHA, OIDC not long-lived keys, least-priv tokens), **LLM/AI** (prompt injection; never let model output drive a privileged action without validation + allowlist), **cloud/infra** (IAM least-privilege, encryption, no public DBs).
- Threat-model with **STRIDE**; verify against **OWASP Top 10 / ASVS**.
- Two modes: **daily** zero-noise high-confidence gate vs **deep** periodic exhaustive audit with trend tracking.
- Real secret leak → **rotate first**, then purge from history, then sweep for similar.
- **Building an action-taking tool/agent/automation?** Make it safe by default: schema-validate inputs, **default to dry-run**, bound the scope (timeouts/max-items/cost), be idempotent, support rollback, and gate destructive ops on explicit confirmation. (Design-time complement to the `destructive-command-guard` hook.)

Complements `web-security` (frontend XSS/CSP) and the `iam-auditor` agent (AWS IAM). Use the built-in `/security-review` for a quick diff pass; this skill is the whole-system view.
