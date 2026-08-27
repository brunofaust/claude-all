## Pre-PR verification — `verification-loop` skill
**Before opening a PR**, run six gates: lint/format → types → tests → coverage → security/secrets → diff review. Never claim "ready to merge" without all green.

Also apply skills matching what the change touches:
- Python → `brunofaust-python-style`; `test-author` for gaps; `alembic-migration` if migrations
- React/frontend → `brunofaust-frontend-style`, `vercel-composition-patterns`, `web-design-guidelines`
- User-facing web → the `brunofaust-frontend-style` security reference, `seo`
- AWS/IaC → `aws-architecture`, `aws-cost-optimization` for new resources
- New non-trivial code → `research-before-build`
- Always → `code-review-discipline`, `adversarial-verification`
