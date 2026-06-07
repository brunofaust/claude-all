## Code review discipline — `code-review-discipline` skill
Apply for any review task (code, security, SEO, migration, architecture).

Rules: PR merge-readiness pre-check first; report-only (never silently refactor). Verdict: CRITICAL→BLOCK / HIGH→WARN / MEDIUM/LOW→INFO. Numeric gates: function <50 lines, file <800, nesting <4. Don't report formatter-fixable style — route to `lint-fixer`.
