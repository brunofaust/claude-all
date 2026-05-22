# Project documentation + changelog patterns

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

**CHANGELOG Format (Keep a Changelog):**

It should follow the format defined on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

***Guiding Principles***

- Changelogs are for humans, not machines.
- There should be an entry for every single version.
- The same types of changes should be grouped.
- Versions and sections should be linkable.
- The latest version comes first.
- The release date of each version is displayed.
- Mention whether you follow Semantic Versioning.

***Types of changes***

- **Added** for new features.
- **Changed** for changes in existing functionality.
- **Deprecated** for soon-to-be removed features.
- **Removed** for now removed features.
- **Fixed** for any bug fixes.
- **Security** in case of vulnerabilities.

```markdown
# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- New feature X

### Changed
- Modified behavior of Y

### Removed
- Configuration file in version 0.3.0

### Fixed
- Bug in Z

## [1.1.1] - 2023-03-05
```

## Documentation Discipline

**Rule:** Documentation is part of every commit. Stale docs are worse than no docs.

### Mandatory files in every project

- `README.md` — project overview, setup, usage (root)
- `CLAUDE.md` — AI-facing: file paths, conventions, common tasks (root + per resource folder)
- `ARCHITECTURE.md` — system design, component relationships, data flow
- `CHANGELOG.md` — every user-facing change, Keep a Changelog format
- `TODO.md` — pending work, blocked items, deferred decisions

### Granularity rule

- Root `CLAUDE.md` = orchestration, conventions, where to look
- Resource `CLAUDE.md` (e.g. `aws_resources/lambdas/dispatcher/CLAUDE.md`) = that resource only
- Parent folder `CLAUDE.md` (e.g. `aws_resources/CLAUDE.md`) = connection points between children

### Pre-commit checklist (PR template)

- [ ] CHANGELOG.md entry under `[Unreleased]`
- [ ] README.md reflects new setup steps, env vars, or commands
- [ ] Root CLAUDE.md updated if conventions, paths, or workflows changed
- [ ] Resource CLAUDE.md updated if entry point, trigger, or dependencies changed
- [ ] ARCHITECTURE.md updated if components/relationships changed
- [ ] TODO.md reconciled

**Rule:** A code change without doc update = incomplete PR. Block merge.

### Enforcement layers

1. **Local (prek):**
   - `scripts/precommit_changelog.sh` — fails if src/ changed but CHANGELOG.md not.
   - `scripts/precommit_docs.sh` — fails if code changed but no .md updated.
   - `scripts/precommit_resource_docs.sh` — fails if aws_resources/<name>/ changed but its CLAUDE.md not.

2. **Commit message (prek):**
   - Commitizen `commit-msg` hook for conventional commits.

3. **PR (GitHub Actions):**
   - `dangoslen/changelog-enforcer@v3.7.0` for CHANGELOG gate.
   - Custom workflow with `tj-actions/changed-files` for docs gate.
   - Skip via labels: `skip-changelog`, `skip-docs`, `dependencies`.

4. **Branch protection:**
   - Require status checks: Changelog Check, Docs Discipline.

**Anti-circumvention:** Never bypass docs hooks with `--no-verify` unless explicitly authorized. The hooks exist because past PRs broke prod due to stale CLAUDE.md trigger maps.

### Example prek hook scripts

`scripts/precommit_changelog.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
STAGED=$(git diff --cached --name-only --diff-filter=ACMR)
CODE=$(echo "$STAGED" | grep -E '^src/' | grep -v -E '^tests/|\.md$' || true)
[[ -z "$CODE" ]] && exit 0
echo "$STAGED" | grep -q '^CHANGELOG\.md$' && exit 0
echo "❌ src/ changed but CHANGELOG.md not updated. Add entry under [Unreleased]."
exit 1
```

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
  { id = "changelog-updated", entry = "scripts/precommit_changelog.sh", language = "system", pass_filenames = false },
  { id = "docs-updated", entry = "scripts/precommit_docs.sh", language = "system", pass_filenames = false },
  { id = "resource-claude-md", entry = "scripts/precommit_resource_docs.sh", language = "system", pass_filenames = false }
]
```

### Example GitHub Action — `.github/workflows/changelog.yml`

```yaml
name: Changelog Check
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review, labeled, unlabeled]
jobs:
  changelog:
    runs-on: ubuntu-latest
    steps:
      - uses: dangoslen/changelog-enforcer@v3.7.0
        with:
          changeLogPath: 'CHANGELOG.md'
          skipLabels: 'skip-changelog,dependencies,docs-only'
          missingUpdateErrorMessage: 'Add an entry to CHANGELOG.md under [Unreleased].'
```
