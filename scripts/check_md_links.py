#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With --json flag, emits a machine-readable JSON object to stdout instead of the
human-readable report. The JSON shape is:
{
  "passed": bool,                    # overall pass/fail status
  "markdown_files_scanned": int,     # number of .md files inspected
  "links_resolved": int,             # total relative links resolved
  "resources_checked": int,          # number of resources checked for README linkage
  "files_skipped": int,              # number of vendored files skipped
  "broken_links": [                  # list of broken relative links
    {
      "file": str,                   # path relative to repo root
      "line": int,                   # line number (1-indexed)
      "target": str,                 # raw link target from markdown
      "resolved_path": str           # resolved absolute path that did not exist
    }
  ],
  "unlinked_resources": [            # list of resources not linked from README
    {
      "kind": str,                   # "skill" or "agent"
      "name": str,                   # resource name
      "path": str                    # path relative to repo root
    }
  ]
}
Diagnostic messages, if any, go to stderr. Exit codes are identical in both modes.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# [label](target) — skip images, absolute URLs, anchors and mailto. A leading `/` is
# a site-absolute URL (the SEO skill's llms.txt examples), never a repo path.
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "#", "tel:", "/")
FENCE = re.compile(r"^\s*(```|~~~)")
# Inline code spans are not links: `def first[T](...)` reads as [T](...).
CODE_SPAN = re.compile(r"`[^`]*`")


def is_vendored(path: Path, registry: list[dict]) -> bool:
    for entry in registry:
        base = ROOT / entry["path"]
        if base not in path.parents:
            continue
        if path.name in entry.get("local_only", []):
            return False
        # vendor_mode "dir" copies the whole tree and lists no individual files.
        if entry.get("vendor_mode") == "dir" or path.name in entry.get("files", []):
            return True
    return False


def strip_code_blocks(text: str) -> list[tuple[int, str]]:
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
        ["git", "ls-files", "-z", "*.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ROOT / p for p in out.split("\0") if p]


def check_links(registry: list[dict]) -> tuple[list[dict], int, int, int]:
    """Check markdown links.

    Returns:
        tuple of (broken_links, links_resolved, files_skipped, markdown_files_scanned)
        where:
        - broken_links: list of dicts with keys: file, line, target, resolved_path
        - links_resolved: total number of relative links resolved
        - files_skipped: number of vendored files skipped
        - markdown_files_scanned: number of .md files inspected
    """
    broken_links = []
    links_resolved = 0
    files_skipped = 0
    markdown_files_scanned = 0

    for md in tracked_markdown():
        if is_vendored(md, registry):
            files_skipped += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        markdown_files_scanned += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                links_resolved += 1
                resolved_path = (md.parent / bare).resolve()
                if not resolved_path.exists():
                    broken_links.append(
                        {
                            "file": str(md.relative_to(ROOT)),
                            "line": line_no,
                            "target": target,
                            "resolved_path": str(resolved_path),
                        }
                    )
    return broken_links, links_resolved, files_skipped, markdown_files_scanned


def check_readme_coverage() -> tuple[list[dict], int]:
    """Check README coverage.

    Returns:
        tuple of (unlinked_resources, resources_checked)
        where:
        - unlinked_resources: list of dicts with keys: kind, name, path
        - resources_checked: number of resources checked for README linkage
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    unlinked_resources = []
    resources_checked = 0

    for item in discover([]):
        resources_checked += 1
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            unlinked_resources.append(
                {"kind": item.kind, "name": item.name, "path": str(item.src.relative_to(ROOT))}
            )

    return unlinked_resources, resources_checked


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Check markdown links and README coverage")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    broken_links, links_resolved, files_skipped, markdown_files_scanned = check_links(registry)
    unlinked_resources, resources_checked = check_readme_coverage()

    if args.json:
        # JSON output mode
        result = {
            "passed": len(broken_links) == 0 and len(unlinked_resources) == 0,
            "markdown_files_scanned": markdown_files_scanned,
            "links_resolved": links_resolved,
            "resources_checked": resources_checked,
            "files_skipped": files_skipped,
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }
        print(json.dumps(result))
    else:
        # Human-readable output mode (preserving existing behavior)
        findings = []
        for link in broken_links:
            findings.append(f"{link['file']}:{link['line']}: broken-link -> {link['target']}")
        for resource in unlinked_resources:
            findings.append(
                f"README.md: undocumented -> {resource['kind']}/{resource['name']} "
                f"(add a row linking {resource['path']})"
            )

        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
