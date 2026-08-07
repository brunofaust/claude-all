# Check MD links gate
## Overview

This script enforces two checks in the repository:
1. **Broken links:** Ensures all relative markdown links resolve correctly in non-vendored files.
2. **README coverage:** Verifies every resource is linked in the README.md file.

## JSON Output

When run with the `--json` flag, the script outputs a machine-readable JSON report:

```json
{
  "passed": false,
  "total_files_scanned": 42,
  "broken_links": [
    {
      "file": "docs/skills/python.md",
      "line": 15,
      "target": "../index.html"
    }
  ],
  "unlinked_resources": [
    "skills/java/README.md"
  ],
  "vendored_files_skipped": 10
}
```

Fields:
- `passed`: Boolean indicating if all checks passed.
- `total_files_scanned`: Total number of markdown files checked.
- `broken_links`: List of objects with details about each broken link.
- `unlinked_resources`: List of paths to resources not linked in README.md.
- `vendored_files_skipped`: Number of vendored files skipped in link checks.
