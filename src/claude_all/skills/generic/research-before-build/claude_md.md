## Before building anything new — `research-before-build` skill

**Step 0 of every non-trivial build is a search, not an edit.** Before writing a new feature, module, CLI command/flag, agent, skill, hook, or utility, spend one tool call confirming it does not already exist. Invoke the `research-before-build` skill for anything larger than a one-liner.

**The cheapest and most-missed check is the local one:** grep THIS repo first. Duplicating a command, flag, helper or skill that already ships here is the common failure — it costs one `grep`/`Glob` to rule out and a whole build to discover afterwards. Then widen only as needed: internal codebase → official docs (Context7) → `gh search code/repos` for an 80%-solution → package registries → web.

Red flag: *"I'll just add a `--<flag>` / a small helper for this"* — check whether that flag, helper, or skill is already there **before** the first edit, not after the PR is open.

Reusing beats generating on both token cost and reliability. When you do build, record the one-line reason nothing existing fit.
