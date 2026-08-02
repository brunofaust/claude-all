# Fixed Ruff lint errors
#!/usr/bin/env python
import os
import json
import sys

def find_violations(patterns: list[str], root: str) -> tuple[list[str], int]:
    violations = []
    count = 0
    for path in _find_files_to_check(root):
        count += 1
        with open(path) as f:
            content = json.load(f)
            for pattern in patterns:
                if pattern in content.get("dependencies", {}):
                    violations.append(
                        f"{path} contains restricted dependency: {pattern}"
                    )
    return violations, count

def _find_files_to_check(root: str) -> list[str]:
    # Actual implementation would use glob/path/regex pattern here
    return [os.path.join(root, "claude_all", "example.json")]

def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} '<root_dir>'")
        sys.exit(1)
    root_dir = sys.argv[1]
    violations, count = find_violations(
        patterns=["restricted_deps.json"],
        root=root_dir
    )
    if violations:
        for v in violations:
            print(f"ERROR: {v}")
        sys.exit(1)
    if count == 0:
        print(f"ERROR: No files matched pattern in {root_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"FILES_SCANNED: {count}")
if __name__ == "__main__":
    main()
