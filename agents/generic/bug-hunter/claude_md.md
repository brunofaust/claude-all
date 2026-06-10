### `bug-hunter` (Sonnet) — deep correctness bug hunt over a named scope
| "hunt for bugs in <subsystem>", "review these files for real bugs (not style)", "is this logic correct" | `bug-hunter` |
| Run linters / type-checkers and report gate findings | `code-quality` (Haiku) |
| Review the current PR diff | `/code-review` skill |
| Whole-repo quality scorecard + remediation roadmap | `repo-audit` skill |
⛔ Dispatching without scope — always inline the file list, hot spots (uncommitted diffs, recent churn, tricky domain logic), and bug-class emphasis in the prompt (see `subagent-prompting`)
⛔ Asking it to fix findings — it is read-only; route fixes to the main session or `lint-fixer`
