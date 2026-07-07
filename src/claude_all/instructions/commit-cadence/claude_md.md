## Commit cadence — commit early, commit often

Frequent, even incomplete, commits beat a clean history with nothing saved: they checkpoint progress against lost context and output limits, isolate each change, and make review and rollback tractable. More commits (including WIP) is the goal, not fewer.

- **Commit at least every ~15 minutes of active work, and after every bug fix or self-contained change** — don't wait until the whole task is "done".
- A WIP commit is fine: `git commit -m "wip: <what's in progress>"`. A saved incomplete state beats an unsaved complete one.
- Keep each commit scoped to one logical change and write a real message (Conventional Commits where the repo uses them). Squash later if the repo wants a tidy history.
- This never overrides the safety gates: still branch/worktree first, never commit straight to the default branch, and never commit secrets.
