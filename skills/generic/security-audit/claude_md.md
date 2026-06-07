## Security audit — `security-audit` skill
Apply before releases, threat-modeling features, auditing CVEs, hardening CI/CD, securing LLM integrations, or sweeping for leaked secrets.

Six layers: app (OWASP Top 10), secrets (full git history), dependency supply chain (SBOM + osv-scanner), CI/CD (pin to SHA, OIDC), LLM/AI (prompt injection), cloud/infra (IAM least-priv). Real secret leak → **rotate first**, then purge from history.
