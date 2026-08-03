import json
import sys
from pathlib import Path

SRC = Path(__file__).parent.parent
REPO_ROOT = Path(__file__).resolve().parent

findings = []

manifests = sorted((SRC / "claude_all").rglob("claude-all.json"))
manifests += sorted((SRC / "claude_all").rglob("*.claude-all.json"))

if not manifests:
    print("No manifests found matching patterns:
        'SRC/claude_all/**/*.claude-all.json'
        'SRC/claude_all/**/*.claude-all.json'", file=sys.stderr)
    sys.exit(2)

count = 0

for manifest in manifests:
    rel = manifest.relative_to(REPO_ROOT)
    try:
        config = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        findings.append(f"{rel}: {str(exc)}")
        continue
    
    if "requires" not in config:
        findings.append(f"{rel}: missing 'requires' key")
        continue
    
    known = {
        p.relative_to(REPO_ROOT) for p in (SRC / "claude_all").rglob("*")
        if p.is_file() and p.suffix not in {".claude-all.json", ".json"}
    }
    
    for dep in config["requires"]:
        if dep not in known:
            findings.append(f"{rel}: requires '{dep}' — no such resource")

    count += 1

if findings:
    print("\n".join(findings))
    print(f"\n{len(findings)} failure(s) detected")
    sys.exit(1)

print(f"Checked {count} manifests")

if len(findings) > 0:
    sys.exit(1)

sys.exit(0)
