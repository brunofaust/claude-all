#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

JSON output mode (--json):
{
  "passed": bool,
  "counts": {
    "markdown_files_scanned": int,
    "links_resolved": int,
    "resources_checked": int,
    "files_skipped_vendored": int
  },
  "broken_links": [
    {
      "file": str,          # relative path from repo root to markdown file
      "line": int,          # line number in that file
      "target": str,        # raw link target as found in markdown
      "resolved": str       # absolute path that was checked and did not exist
    }
  ],
  "unlinked_resources": [   # paths of resources not linked from README
    {
      "kind": str,          # kind of resource (e.g., "skill", "agent")
      "name": str,          # name of resource
      "path": str           # relative path from repo root to resource file
    }
  ]
}
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


def check_links(registry: list[dict]) -> tuple[list[dict], dict]:
    """Check markdown links.

    Returns:
        tuple: (findings, counts)
          findings: list of dicts, each representing a broken link with keys:
            file: relative path from repo root to markdown file
            line: line number in that file
            target: raw link target as found in markdown
            resolved: absolute path that was checked and did not exist
          counts: dict with keys:
            markdown_files_scanned: number of markdown files processed (non-vendored and existing)
            links_resolved: number of links checked (after skipping SKIP_PREFIX and empty bare)
            files_skipped_vendored: number of markdown files skipped due to vendored exemption
    """
    findings = []
    counts = {
        "markdown_files_scanned": 0,
        "links_resolved": 0,
        "files_skipped_vendored": 0,
    }
    for md in tracked_markdown():
        if is_vendored(md, registry):
            counts["files_skipped_vendored"] += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        counts["markdown_files_scanned"] += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                counts["links_resolved"] += 1
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    findings.append(
                        {
                            "file": str(rel),
                            "line": line_no,
                            "target": target,
                            "resolved": str((md.parent / bare).resolve()),
                        }
                    )
    return findings, counts


def check_readme_coverage() -> tuple[list[dict], dict]:
    """Check README coverage of resources.

    Returns:
        tuple: (findings, counts)
          findings: list of dicts, each representing an unlinked resource with keys:
            kind: kind of resource (e.g., "skill", "agent")
            name: name of resource
            path: relative path from repo root to resource file
          counts: dict with key:
            resources_checked: number of resources discovered by discover([])
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    findings = []
    for item in items:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            findings.append(
                {
                    "kind": item.kind,
                    "name": item.name,
                    "path": str(item.src.relative_to(ROOT)),
                }
            )
    return findings, {"resources_checked": len(items)}


def _format_human_output(link_findings, coverage_findings) -> list[str]:
    """Format findings as human-readable strings (preserving existing output)."""
    formatted = []
    for finding in link_findings:
        formatted.append(f"{finding['file']}:{finding['line']}: broken-link -> {finding['target']}")
    for finding in coverage_findings:
        formatted.append(
            f"README.md: undocumented -> {finding['kind']}/{finding['name']} "
            f"(add a row linking {finding['path']})"
        )
    return formatted


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="output machine-readable JSON")
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    link_findings, link_counts = check_links(registry)
    coverage_findings, coverage_counts = check_readme_coverage()

    if args.json:
        result = {
            "passed": len(link_findings) + len(coverage_findings) == 0,
            "counts": {
                "markdown_files_scanned": link_counts["markdown_files_scanned"],
                "links_resolved": link_counts["links_resolved"],
                "resources_checked": coverage_counts["resources_checked"],
                "files_skipped_vendored": link_counts["files_skipped_vendored"],
            },
            "broken_links": [
                {
                    "file": f["file"],
                    "line": f["line"],
                    "target": f["target"],
                    "resolved": f["resolved"],
                }
                for f in link_findings
            ],
            "unlinked_resources": [
                {
                    "kind": f["kind"],
                    "name": f["name"],
                    "path": f["path"],
                }
                for f in coverage_findings
            ],
        }
        print(json.dumps(result))
        return 0 if len(link_findings) + len(coverage_findings) == 0 else 1
    else:
        # Human output: preserve existing format exactly
        for line in _format_human_output(link_findings, coverage_findings):
            print(line)
        total_findings = len(link_findings) + len(coverage_findings)
        if total_findings:
            print(f"\n{total_findings} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
