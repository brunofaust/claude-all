---
name: security-audit
description: >-
  Holistic security audit + threat modeling across the whole stack — application (OWASP Top 10),
  secrets, dependency supply chain, CI/CD pipeline, LLM/AI, and cloud/infra. Use when: doing a
  security pass before a release, threat-modeling a feature/service, reviewing auth/authz or input
  handling on the backend, auditing dependencies for CVEs, hardening a CI/CD pipeline, securing an
  LLM-integrated feature (prompt injection, untrusted model output), or sweeping a repo/git history
  for leaked secrets. Two modes: a daily zero-noise high-confidence gate, and a periodic deep audit.
  Complements web-security (frontend XSS/CSP), iam-auditor (AWS IAM), and code-review-discipline
  (output shape). Use the built-in `/security-review` for a quick diff pass; use this for the
  whole-system view.
disable-model-invocation: false
user-invocable: true
---

# Security Audit

Whole-system security, not just the diff. Pick a **mode** and walk the **six layers**, scoring
findings with the `code-review-discipline` severity model (CRITICAL→BLOCK … INFO).

## Two modes

- **Daily (zero-noise gate)** — high-confidence only (≥ ~8/10). Fast, on every PR/release. Report a
  finding only if you'd stake the release on it. No speculative "could maybe" noise.
- **Deep (periodic)** — exhaustive, lower confidence bar (~2/10), run monthly/quarterly or before a
  big launch. Track findings across runs (trend: new / fixed / recurring).

## Frameworks

- **OWASP Top 10** + **ASVS** for application/web verification.
- **STRIDE** for threat modeling a feature/data-flow:

  | Threat | Question | Mitigation |
  | --- | --- | --- |
  | **S**poofing | Can an actor pretend to be someone else? | strong authn, mTLS, signed tokens |
  | **T**ampering | Can data/requests be modified in transit/at rest? | integrity checks, signing, validation |
  | **R**epudiation | Can an action be denied later? | audit logs, signed events |
  | **I**nfo disclosure | Can data leak? | encryption, least-privilege, no secrets in logs |
  | **D**enial of service | Can it be overwhelmed? | rate limits, quotas, timeouts, backpressure |
  | **E**levation of privilege | Can a user gain more rights? | authz checks at every boundary |

## The six layers

1. **Application** (OWASP Top 10) — broken access control (authz on *every* server endpoint, not the
   UI), injection (SQL/NoSQL/command/template), SSRF, insecure deserialization, auth/session, mass
   assignment. (Frontend XSS/CSP/Server-Actions → `web-security`.) **Validate every input at the
   trust boundary**; rate-limit every endpoint.
2. **Secrets** — no secret in code, logs, or client bundles. **Secrets archaeology**: scan full git
   *history* (`gitleaks detect`, `trufflehog`), not just HEAD. Vault/Secrets-Manager + rotation;
   validate required secrets exist at startup (fail fast).
3. **Dependency supply chain** — generate an **SBOM**; scan for CVEs (`osv-scanner`, `pip-audit`,
   `npm audit`, `cargo audit`); pin + verify lockfile integrity; watch for typosquatting / sudden
   maintainer changes; Dependabot/Renovate on. A 10-star package handling untrusted input is a risk.
4. **CI/CD pipeline** — pin actions to a **commit SHA**, not a moving tag; least-privilege workflow
   tokens; **OIDC** over long-lived cloud keys; protected branches + required reviews; no secrets
   echoed in logs; sign artifacts/commits; treat the pipeline as production (it has prod creds).
5. **LLM / AI** — **prompt injection** (untrusted text steering the model); **trust boundary**:
   never let model output drive a privileged action (DB write, shell, payment, tool call) without
   validation + an allowlist; constrain tool/function calling; validate/sanitize model output as
   untrusted input; keep secrets/PII out of prompts and logs; guard against data exfiltration via
   crafted inputs. (Pairs with the `code-review-discipline` LLM-trust-boundary lens.)
6. **Cloud / infra** — IAM least-privilege (→ `iam-auditor` for AWS), encryption at rest + in transit,
   minimal network exposure (security groups, no public DBs), audit logging + alerting on.

## Output

Use the `code-review-discipline` format: severity-scored findings with file:line + a concrete fix.
For the **daily** mode, only CRITICAL/HIGH that you're confident in. For **deep**, include MEDIUM/LOW
and a trend line (new vs recurring vs fixed since last run). Always: incident protocol for a real
secret leak → **rotate first**, then purge from history, then sweep for similar.

## Anti-patterns

| Anti-pattern | Why | Instead |
| --- | --- | --- |
| Authz enforced only in the UI | the API is public | check authz on every server endpoint |
| Scanning only HEAD for secrets | the leak is in history | scan full git history (gitleaks/trufflehog) |
| Pinning CI actions to a tag (`@v4`) | tags move → supply-chain hijack | pin to a commit SHA |
| Long-lived cloud keys in CI | broad blast radius if leaked | OIDC short-lived creds |
| LLM output → `eval`/SQL/shell/tool unchecked | prompt-injection RCE/data loss | validate + allowlist before any privileged action |
| Daily audit full of "could maybe" findings | alert fatigue → ignored | zero-noise high-confidence gate |

## Enforcement / tooling

- Secrets: `gitleaks` (history), `trufflehog`. Code: `semgrep` (rulesets), `bandit` (Python),
  `codeql`. Deps: `osv-scanner`/`pip-audit`/`npm audit`/`cargo audit`, Dependabot/Renovate.
  Containers/IaC: `trivy`, `checkov`/`tfsec`. Wire the high-signal ones into CI (and prek where it
  fits). AWS IAM → `iam-auditor` agent; frontend → `web-security` skill.
