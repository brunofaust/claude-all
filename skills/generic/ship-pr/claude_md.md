## Opening a PR — use the `/ship-pr` workflow
When about to open a pull request (the user says "open a PR", "raise a PR", "ship this for review", or you're finishing a change that's going out for review), run the **`/ship-pr`** skill instead of committing + opening the PR ad hoc. It gates the change through lint → tests → verification-loop → code-review (block on Block findings) → conditional security-review BEFORE the commit, then opens a **draft** PR after confirmation.

Rule: don't open a PR over un-run gates or an unreviewed diff. Skipping straight to `git commit` + PR-open is the anti-pattern this prevents. For a quick local commit with no review/PR, use `/ship` (lighter). Confirm before the commit and again before opening the PR; default the PR to draft; never enable auto-merge.
