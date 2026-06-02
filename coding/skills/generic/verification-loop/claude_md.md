## Pre-PR verification — verification-loop skill (+ stack-aware skill checklist)

**Before opening a PR**, apply the `verification-loop` skill — six explicit gates (lint/format → types → tests → coverage → security/secrets → diff review) ending in a READY / NOT READY verdict. Never claim "ready to merge" without the gates green.

As part of that pass, also apply the skills relevant to **what the change actually touches** (only the ones installed / applicable):

- **Python** → `brunofaust-python-style`; `test-author` for coverage gaps; `alembic-migration` if there are migrations.
- **React / frontend** → `react-correctness`, `react-testing`, `web-design-guidelines`.
- **Any user-facing web surface** → `web-security` (XSS / secrets / CSP / Server Actions) and `seo` (meta / structured data / Core Web Vitals).
- **AWS / IaC** → `aws-architecture`, and `aws-cost-optimization` for new resources.
- **New non-trivial code** → `research-before-build` first (reuse before net-new).
- **Always** → `code-review-discipline` (review shape + numeric gates) and `adversarial-verification` (quote evidence before any "done" / "it works" / "tests pass").

Run lint/tests through the `code-quality` and `test-runner` agents; fix findings with `lint-fixer`.
