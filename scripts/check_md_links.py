#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"(?<!!)\[.*?\]\(([^)\s]+)\)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "#", "tel:", "/")
FENCE = re.compile(r"^```.*?$", re.MULTILINE)


@staticmethod
def strip_code_blocks(text: str) -> str:
    return FENCE.sub('', text, count=0)

@staticmethod
def is_vendored(path: Path, registry: list[dict]) -> bool:
    """
    Upstream-owned files are exempt: kept byte-identically, so their
    own relative links point at an upstream tree we deliberately did not copy.
    `local_only` files live in the same directory but are OURS —
    they stay checked.
    """
    for entry in registry:
        base = ROOT / entry['path']
        if base not in path.parents:
            continue
        if path.name in entry.get('local_only', []):
            return False
        if entry.get('vendor_mode') == 'dir' or path.name in entry.get('files', []):
            return True
    return False

@staticmethod
def tracked_markdown() -> list[Path]:
    """
    Resources include:
    - mkdocs.yml (for nav links in markdown files)
    - README.md
    - CLAUDE.md files (in the repo root and per-resource)
    - all markdown files in skills/ and agents/
    """
    md_files = []
    for path in Path(ROOT).rglob('*'):
        if path.is_file() and path.suffix == '.md':
            md_files.append(path)
    for path in Path(ROOT).rglob('mkdocs.yml'):
        md_files.append(path)
    return md_files

def check_links(registry: list[dict]) -> list[dict]:
    """
    Returns: One finding string per broken link or missing README entry.
    """
    findings = []
    for md in tracked_markdown():
        if not md.exists():
            continue
        for line_no, line in enumerate(md.open('r', encoding='utf-8'), start=1):
            line_text = FENCE.sub('', line, count=0)
            for target in LINK.findall(line_text):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split('#')[0]
                if not bare:
                    continue
                if not (md.parent / bare).resolve().exists():
                    findings.append(f"{md.relative_to(ROOT)}:{line_no}: broken-link -> {target}")

    readme_links = set()
    readme = ROOT / 'README.md'
    if readme.exists():
        with readme.open('r', encoding='utf-8') as f:
            for line in f:
                for target in LINK.findall(line):
                    readme_links.add(target.split('#')[0])

    all_files = {p.name for p in tracked_markdown()} | {p.name for p in Path(ROOT).rglob('*') if p.is_file() and p.suffix != '.md'}
    unlinked = all_files - readme_links
    for resource in unlinked:
        findings.append(f"Unlinked resource: {resource}")

    return findings


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Check markdown links and README coverage.')
    parser.add_argument('--json', action='store_true', help='Output in JSON format')
    args = parser.parse_args()

    registry = json.loads((ROOT / 'vendored.json').read_text()) if (ROOT / 'vendored.json').exists() else []
    findings = check_links(registry)

    if args.json:
        result = {
            "status": "fail" if findings else "pass",
            "markdown_files_scanned": len([p for p in Path(ROOT).rglob('*') if p.suffix == '.md']),
            "links_checked": 0,
            "resources_verified": 0,
            "files_skipped_vendored": 0,
            "broken_links": []
        }

        for finding in findings:
            if 'broken-link' in finding:
                parts = finding.split(':')
                result["broken_links"].append({
                    "file_path": parts[0],
                    "line_number": parts[1],
                    "target": parts[2]
                })
            elif 'Unlinked resource' in finding:
                # TO DO: Implement unlinked resources in JSON
                pass

        print(json.dumps(result, indent=2))
    else:
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).")
            return 1
        return 0

if __name__ == '__main__':
    sys.exit(main())
