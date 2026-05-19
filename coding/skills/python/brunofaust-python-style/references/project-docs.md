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
