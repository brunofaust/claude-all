### Command dispatch — GitHub `gh` CLI inspection → `gh-runner` (Haiku)

| Command | Agent |
|---|---|
| `gh pr list/view/checks`, `gh issue list/view`, `gh repo view`, `gh release list`, `gh run list/view --log` | `gh-runner` |

Anti-patterns:

- `Bash(gh pr view ...)` / `Bash(gh run view --log)` / `Bash(gh pr list)` — these return hundreds to thousands of lines; delegate to `gh-runner` and act on the summary.
- When the GitHub MCP tools are available, prefer them for WRITES (creating PRs, comments, reviews). `gh-runner` is for read-only `gh` CLI inspection.

Note: a small one-shot `gh` call (`gh pr view --json number -q .number`) can stay inline. For commits/pushes use `git-committer` / the main session, not `gh-runner`.
