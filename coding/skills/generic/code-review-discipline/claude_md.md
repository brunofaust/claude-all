## Code review discipline — code-review-discipline skill

For any review-style task (code review, security review, SEO review, migration review, architecture review), apply the `code-review-discipline` skill — it defines the output shape and verdict so every reviewer is consistent.

- PR merge-readiness pre-check first; **report-only** (never silently refactor while reviewing).
- Mechanical verdict from severities: CRITICAL → BLOCK · HIGH → WARN · MEDIUM/LOW → INFO. Don't invent new severities or override the verdict.
- Numeric gates as findings: function < 50 lines, file < 800, nesting < 4; per-layer coverage table.
- High-stakes diffs → run a **split-role review panel** (factual / senior-eng / security / consistency / redundancy) in parallel, then merge findings.

Don't report formatter-fixable style as findings — that's unfixed lint (route to `lint-fixer`).
