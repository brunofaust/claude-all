#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

Usage:
    python scripts/check_md_links.py          human-readable report (default)
    python scripts/check_md_links.py --json   one JSON object on stdout instead

The exit code is 0 when the gate passes and 1 on any finding, in both modes.

JSON shape (--json):
    {
      "pass": bool,
      "counts": {
        "markdown_files_scanned": int,  # tracked .md files read from disk (not vendored)
        "vendored_files_skipped": int,  # tracked .md files exempt as vendored
        "links_checked": int,           # relative link occurrences checked against disk
        "links_resolved": int,          # of those, the ones whose target exists
        "resources_checked": int        # len(discover([])): every discovered resource
      },
      "broken_links": [
        {"file": str, "line": int, "target": str, "resolved": str}
      ],
      "unlinked_resources": [
        {"kind": str, "name": str, "path": str}
      ]
    }

Paths are repo-relative POSIX strings. `target` is the raw link text as written;
`resolved` is the repo-relative path it points at (it starts with `../` when the
link escapes the repo). `path` in `unlinked_resources` is the resource's source file.

Error (--json only): when the check itself cannot run (for example `git ls-files`
fails), stdout carries the error object below instead, the exit code is 1, and the
traceback goes to stderr:
    {"pass": false, "error": {"type": str, "message": str}}

Counts are raw. There is no vacuous-pass flag: a caller that must reject a run which
inspected zero files compares `markdown_files_scanned` against zero itself. The
exit code does not change for a zero-file run.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# [label](target) — skip images, absolute URLs, anchors and mailto. A leading `/` is
# a site-absolute URL (the SEO skill's llms.txt examples), never a repo path.
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "#", "tel:", "/")
FENCE = re.compile(r"^\s*(```|~~~)")
# Inline code spans are not links: `def first[T](...)` reads as [T](...).
CODE_SPAN = re.compile(r"`[^`]*`")


@dataclass
class LinkScan:
    markdown_files_scanned: int = 0
    vendored_files_skipped: int = 0
    links_checked: int = 0
    links_resolved: int = 0
    broken_links: list[dict[str, str | int]] = field(default_factory=list)


@dataclass
class CoverageScan:
    resources_checked: int = 0
    unlinked_resources: list[dict[str, str]] = field(default_factory=list)


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


def check_links(registry: list[dict]) -> LinkScan:
    scan = LinkScan()
    for md in tracked_markdown():
        if is_vendored(md, registry):
            scan.vendored_files_skipped += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        scan.markdown_files_scanned += 1
        rel = md.relative_to(ROOT).as_posix()
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                scan.links_checked += 1
                resolved = (md.parent / bare).resolve()
                if resolved.exists():
                    scan.links_resolved += 1
                    continue
                scan.broken_links.append(
                    {
                        "file": rel,
                        "line": line_no,
                        "target": target,
                        "resolved": Path(os.path.relpath(resolved, ROOT)).as_posix(),
                    }
                )
    return scan


def check_readme_coverage() -> CoverageScan:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    scan = CoverageScan(resources_checked=len(items))
    for item in items:
        path = item.src.relative_to(ROOT).as_posix()
        if f"]({path})" not in readme:
            scan.unlinked_resources.append({"kind": item.kind, "name": item.name, "path": path})
    return scan


def run_checks() -> tuple[LinkScan, CoverageScan]:
    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    return check_links(registry), check_readme_coverage()


def human_findings(links: LinkScan, coverage: CoverageScan) -> list[str]:
    findings = [
        f"{b['file']}:{b['line']}: broken-link -> {b['target']}" for b in links.broken_links
    ]
    findings.extend(
        f"README.md: undocumented -> {u['kind']}/{u['name']} (add a row linking {u['path']})"
        for u in coverage.unlinked_resources
    )
    return findings


def json_report(links: LinkScan, coverage: CoverageScan) -> dict:
    broken = links.broken_links
    unlinked = coverage.unlinked_resources
    return {
        "pass": not broken and not unlinked,
        "counts": {
            "markdown_files_scanned": links.markdown_files_scanned,
            "vendored_files_skipped": links.vendored_files_skipped,
            "links_checked": links.links_checked,
            "links_resolved": links.links_resolved,
            "resources_checked": coverage.resources_checked,
        },
        "broken_links": broken,
        "unlinked_resources": unlinked,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check markdown links and README coverage.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a single JSON object on stdout instead of the human-readable report",
    )
    args = parser.parse_args(argv)

    if not args.json:
        links, coverage = run_checks()
        findings = human_findings(links, coverage)
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0

    try:
        links, coverage = run_checks()
    except Exception as exc:
        traceback.print_exc()
        error = {"pass": False, "error": {"type": type(exc).__name__, "message": str(exc)}}
        print(json.dumps(error, indent=2))
        return 1
    report = json_report(links, coverage)
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
