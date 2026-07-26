# Project documentation patterns

> Reference page for the `brunofaust-python-style` skill. The main SKILL.md keeps a condensed summary; this file holds the full depth.

### Project Documentation

**README Structure:**

```markdown
# Project Name

Brief description of what the project does.

## Installation

\`\`\`bash
uv sync
\`\`\`

## Quick Start

\`\`\`python
from myproject import Client

client = Client(api_key="...")
result = client.process(data)
\`\`\`

## Configuration

Document environment variables and configuration options.

## Development

\`\`\`bash
uv sync
uv run pytest
\`\`\`
```

## Documentation Discipline

**Rule:** Documentation is part of every commit. Stale docs are worse than no docs.

### Mandatory files in every project

- `README.md` — project overview, setup, usage (root)
- `CLAUDE.md` — AI-facing: file paths, conventions, common tasks (root + per resource folder)
- `ARCHITECTURE.md` — system design, component relationships, data flow
- `TODO.md` — pending work, blocked items, deferred decisions

**No `CHANGELOG.md`.** A hand-maintained changelog is a shared-file merge-conflict
magnet on every parallel PR — release notes come from Conventional Commits history
(`git log`, `python-semantic-release`, or the GitHub "generate release notes"
feature) instead of a file every branch has to rebase through.

### Granularity rule

- Root `CLAUDE.md` = orchestration, conventions, where to look
- Resource `CLAUDE.md` (e.g. `aws_resources/lambdas/dispatcher/CLAUDE.md`) = that resource only
- Parent folder `CLAUDE.md` (e.g. `aws_resources/CLAUDE.md`) = connection points between children

### Pre-commit checklist (PR template)

- [ ] README.md reflects new setup steps, env vars, or commands
- [ ] Root CLAUDE.md updated if conventions, paths, or workflows changed
- [ ] Resource CLAUDE.md updated if entry point, trigger, or dependencies changed
- [ ] ARCHITECTURE.md updated if components/relationships changed
- [ ] TODO.md reconciled

**Rule:** A code change without doc update = incomplete PR. Block merge.

### Enforcement layers

1. **Local (prek):**

    - `scripts/precommit_docs.sh` — fails if code changed but no .md updated.
    - `scripts/precommit_resource_docs.sh` — fails if aws_resources/<name>/ changed but its CLAUDE.md not.

1. **Commit message (prek):**

    - Commitizen `commit-msg` hook for conventional commits.

1. **PR (GitHub Actions):**

    - Custom workflow with `tj-actions/changed-files` for docs gate.
    - Skip via labels: `skip-docs`, `dependencies`.

1. **Branch protection:**

    - Require status checks: Docs Discipline.

**Anti-circumvention:** Never bypass docs hooks with `--no-verify` unless explicitly authorized. The hooks exist because past PRs broke prod due to stale CLAUDE.md trigger maps.

### Example prek hook scripts

`scripts/precommit_docs.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
STAGED=$(git diff --cached --name-only --diff-filter=ACMR)
CODE=$(echo "$STAGED" | grep -E '^(src/|frontend/src/|infra/)' | grep -v '\.md$' || true)
DOCS=$(echo "$STAGED" | grep -E '\.md$' || true)
if [[ -n "$CODE" && -z "$DOCS" ]]; then
  echo "❌ Code changed but no .md updated. Update README/CLAUDE/ARCHITECTURE."
  exit 1
fi
exit 0
```

`scripts/precommit_resource_docs.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
STAGED=$(git diff --cached --name-only --diff-filter=ACMR)
RESOURCE_DIRS=$(echo "$STAGED" | grep -oE '^src/[^/]+/aws_resources/(lambdas|ecs_tasks|batch_jobs|step_functions|codebuild_projects|glue_jobs)/[^/]+' | sort -u || true)
[[ -z "$RESOURCE_DIRS" ]] && exit 0
for dir in $RESOURCE_DIRS; do
  if ! echo "$STAGED" | grep -q "^${dir}/CLAUDE.md$"; then
    echo "❌ $dir/ changed but $dir/CLAUDE.md not updated."
    exit 1
  fi
done
exit 0
```

### Example `prek.toml` additions

```toml
[[repos]]
repo = "http://github.com/commitizen-tools/commitizen"
rev = "v3.29.0"
hooks = [{ id = "commitizen", stages = ["commit-msg"] }]

[[repos]]
repo = "local"
hooks = [
  { id = "docs-updated", entry = "scripts/precommit_docs.sh", language = "system", pass_filenames = false },
  { id = "resource-claude-md", entry = "scripts/precommit_resource_docs.sh", language = "system", pass_filenames = false }
]
```
