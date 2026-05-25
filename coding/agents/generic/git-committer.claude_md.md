### Command dispatch — git commit → `git-committer` (Haiku)

Anti-pattern:
- `Bash(git commit ...)` in any repo — delegate to `git-committer`. If the repo has a pre-commit hook (prek, husky, pre-commit framework), hook output is 40-100 lines per attempt and floods the main session; the agent captures it, handles autofix retries silently, and returns a tight pass/fail summary.
- `Bash(git add ... && git commit ...)` — same; the whole stage+commit cycle belongs in the agent.
