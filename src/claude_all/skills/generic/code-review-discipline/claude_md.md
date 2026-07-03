## Code review discipline — `code-review-discipline` skill
Rules: PR merge-readiness pre-check first; report-only (never silently refactor). Verdict: any CRITICAL or HIGH→BLOCK / only MEDIUM→WARNING / only LOW or INFO→APPROVE. Numeric gates: function <50 lines, file <800, nesting <4. Don't report formatter-fixable style — route to `lint-fixer`.
