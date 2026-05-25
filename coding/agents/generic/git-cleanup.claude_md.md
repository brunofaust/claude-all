### Command dispatch — end-of-session cleanup → `git-cleanup` (Haiku)

Trigger when user says "cleanup", "session cleanup", "end of session", "clean the repo",
"too many branches/worktrees", or any phrasing suggesting they want to tidy the local git
state **after finishing a Claude Code session**.

Anti-patterns:
- `Bash(git branch -d ...)` / `Bash(git worktree remove ...)` chained in main session — each is a
  guess; the cleanup agent runs a safety scan first and will never delete uncommitted or unpushed work.
- Asking "which branches can I delete?" without first checking for unsafe state — the agent blocks on
  uncommitted files and unpushed commits before presenting any deletion plan.
