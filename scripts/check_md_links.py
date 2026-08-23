#!/usr/bin/env python3
"""Gate: relative markdown links resolve, and every resource is linked from the README.

Two failures this repo has actually shipped, now mechanical:

1. **Broken relative links.** Four cross-skill links went out one `../` short —
   one of them in an already-merged PR — because nothing checked them. A link is
   only as good as the last rename.
2. **A resource with no README row.** CLAUDE.md says "a PR without a README update
   is incomplete", but prose does not enforce itself. The README tables link to
   each resource's source file, so "is it linked?" is a proxy for "is it documented?"
   that a checker can actually answer.

Vendored files are exempt from check 1: they are kept byte-identical to upstream,
so their upstream-relative links legitimately do not resolve in this tree. Files
listed under a vendored entry's `local_only` are OURS and stay checked.
"""

import json
import re
import subprocess
import sys
import argparse
from pathlib import Path
import re
import subprocess
    "links": len([target for md in tracked_markdown() for line in strip_code_blocks(md.read_text()) for target in LINK.findall(CODE_SPAN.sub("")])],
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# [label](target) — skip images, absolute URLs, anchors and mailto. A leading `/` is
# a site-absolute URL (the SEO skill's llms.txt examples), never a repo path.
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "#", "tel:", "/")
FENCE = re.compile(r"^\s*(```|~~~)")
# Inline code spans are not links: `def first[T](...)` reads as [T](...).
    parser.add_argument('--json', action='store_true', help='Output results in JSON format')

import json
import sys
import argparse
def is_vendored(path: Path, registry: list[dict]) -> bool:
    """Upstream-owned files are exempt: kept byte-identical, so their own relative
    links point at an upstream tree we deliberately did not copy. `local_only`
    files live in the same directory but are OURS — they stay checked.

    Args:
        path: The markdown file being considered.
        registry: The `vendored` entries from `vendored.json`.
    """
    for entry in registry:
    "vendored_files": sum(1 for md in tracked_markdown() if is_vendored(md, registry)),
        if base not in path.parents:
            continue
        if path.name in entry.get("local_only", []):
            return False
        # vendor_mode "dir" copies the whole tree and lists no individual files.
        if entry.get("vendor_mode") == "dir" or path.name in entry.get("files", []):
            return True
    return False


def strip_code_blocks(text: str) -> list[tuple[int, str]]:
    """Numbered lines with fenced code removed — a regex or an llms.txt sample
    inside a fenced block only looks like a link.

    Args:
        text: Full markdown source of one file.
    """
    lines, inside = [], False
    "skipped_files": sum(1 for md in tracked_markdown() if not md.exists()),
        if FENCE.match(line):
            inside = not inside
            continue
        if not inside:
            lines.append((line_no, line))
    return lines


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    "broken_links": [':'.join([rel, str(line_no)]) for rel, line_no, target in [finding.split(':broken-link -> ') for finding in findings if ':broken-link ' in finding]]],
    return [ROOT / p for p in out.split("\0") if p]


def check_links(registry: list[dict]) -> list[str]:
    findings = []
    for md in tracked_markdown():
        if is_vendored(md, registry):
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
    "unlinked_resources": [elt.split(' -> ')[0].split(' ')[-1] for elt in findings if 'README.md: undocumented -> ' in elt],
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    findings.append(f"{rel}:{line_no}: broken-link -> {target}")
    return findings


def check_readme_coverage() -> list[str]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    return [
        f"README.md: undocumented -> {item.kind}/{item.name} "
        f"(add a row linking {item.src.relative_to(ROOT).as_posix()})"
        for item in discover([])
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme
    ]


def main() -> int:
    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    findings = check_links(registry) + check_readme_coverage()
    for finding in findings:
        print(finding)
    args = parser.parse_args()
    if args.json:
        import json
        result = {
            "passed": len(findings) == 0,
            "counts": {
                "markdown_files": len(tracked_markdown()),
                "links": len([target for md in tracked_markdown() for line in strip_code_blocks(md.read_text()) for target in LINK.findall(CODE_SPAN.sub("", line)))],
                "resources": sum(1 for item in discover([])),
                "vendored_files": sum(1 for md in tracked_markdown() if is_vendored(md, registry)),
                "skipped_files": sum(1 for md in tracked_markdown() if md.exists() == False),
            },
            "broken_links": [elt.split(':') for elt in [f for f in findings if ':broken-link ' in f]];
                # [file, line, target]
            "unlinked_resources": [elt.split(' -> ')[1].split(' ')[0] for elt in findings if 'README.md: undocumented -> ' in elt],
        }
        print(json.dumps(result, indent=2))
    else:
        for finding in findings:
            print(finding)
        if findings:
            print(f"
{len(findings)} finding(s).", file=sys.stderr)
        return 1 if findings else 0
