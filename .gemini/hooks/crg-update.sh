#!/usr/bin/env bash
# code-review-graph: incremental update after write/replace (Gemini CLI hook)
# Must output ONLY JSON on stdout. Low-noise: no systemMessage.
set -euo pipefail

cat > /dev/null || true

code-review-graph update --skip-flows --repo "/Users/bfaust/Library/CloudStorage/OneDrive-Personal/Documents/My Git/claude-all/.claude/worktrees/feat+compact-context" >/dev/null 2>&1 || true
echo '{"suppressOutput": true}'
exit 0
