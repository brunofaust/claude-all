import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# [label](target) — skip images, absolute URLs, anchors and mailto. A leading `/` is
# a site-absolute URL (the SEO skill's llms.txt examples), never a repo path.
LINK = re.compile(r"(?!{})\[(.*?)\]((?:[^)\s]+)(?:\s+"[^"]*")?)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "#", "tel:", "/")
FENCE = re.compile(r"^\s*(```|~~~)")
# Inline code spans are not links: `def first[T](...)` reads as [T](...).
CODE_SPAN = re.compile(r"`[^`]*`")

def is_vendored(path: Path, registry: list[dict]) -> bool:
    """Upstream-owned files are exempt: kept byte-identical, so their own relative
    links point at an upstream tree we deliberately did not copy. `local_only`
    files live in the same directory but are OURS — they stay checked.
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

def strip_code_blocks(text: str) -> list[tuple[int, str]]:
    """Numbered lines with fenced code removed — a regex or an llms.txt sample
    inside a fenced block only looks like a link.
    """
    lines, inside = [], False
    for line_no, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            inside = not inside
            continue
        if not inside:
            lines.append((line_no, line))
    return lines

def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ['git', 'ls-files', '-z', '*.md'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ROOT / p for p in out.split('\0') if p]

def check_links(registry: list[dict]) -> list[str]:
    """Collect broken links in all markdown files not vendored"""
    findings = []
    for md in tracked_markdown():
        if is_vendored(md, registry):
            continue
        if not md.exists():
            continue
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub('', line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split('#', 1)[0]
                if not bare:
                    continue
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    findings.append(f"{rel}:{line_no}: broken-link -> {target}")
    return findings

def check_readme_coverage() -> list[str]:
    """Finds resources not linked in any README table"""
    sys.path.insert(0, str(ROOT / 'src'))
    from claude_all.cli import discover

    readme = (ROOT / 'README.md').read_text()
    return [
        f"README.md: undocumented -> {item.kind}/{item.name} (add a row linking {item.src.relative_to(ROOT).as_posix()})"
        for item in discover([])
        if f"]({item.src.relative_to(ROOT).as_posix()})]" not in readme
    ]


def generate_json_report(findings: list[str]) -> dict:
    """Create a structured JSON report from findings"""
    report = {
        'overall_status': 'pass' if len(findings) == 0 else 'fail',
        'counts': {
            'markdown_files_scanned': len(tracked_markdown()),
            'total_links_resolved': 0,  # This count requires additional implementation
            'total_resources_checked': 0,  # This count requires additional implementation
            'vendored_files_skipped': 0,  # This count requires additional implementation
        },
        'broken_links': [],
        'unlinked_resources': []
    }

    for finding in findings:
        if 'broken-link' in finding:
            parts = finding.split(':')
            report['broken_links'].append({
                'file': parts[0],
                'line': int(parts[1]),
                'target': parts[2].split('-> ')[1]
            })
        elif 'undocumented' in finding:
            report['unlinked_resources'].append(parts[0])

    return report

def main() -> int:
    registry = json.loads((ROOT / 'vendored.json').read_text()).get('vendored', [])
    findings = check_links(registry) + check_readme_coverage()
    if '--json' in sys.argv:
        report = generate_json_report(findings)
        print(json.dumps(report, indent=2))
        return 1 if findings else 0
    else:
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
        return 0 if not findings else 1

if __name__ == '__main__':
    raise SystemExit(main())
