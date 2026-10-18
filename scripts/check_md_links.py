#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

Usage:
    check_md_links.py          human-readable findings on stdout, count on stderr
    check_md_links.py --json   one JSON object on stdout (nothing else); count on stderr

Exit codes (identical in both modes): 0 when there are no findings, 1 when there
is at least one finding.

JSON shape (`--json`):

    {
      "pass": bool,                 # true iff there are no findings (exit 0)
      "counts": {
        "markdown_scanned": int,    # tracked .md files scanned (not vendored, on disk)
        "vendored_skipped": int,    # tracked .md files exempt as vendored
        "links_resolved": int,      # in-scope relative links whose target exists
        "resources_checked": int    # discovered resources checked against the README
      },
      "broken_links": [             # one entry per relative link that does not resolve
        {
          "file": str,              # repo-relative path of the containing markdown file
          "line": int,              # 1-based line number of the link
          "target": str,            # raw link target as written, e.g. "../x.md#anchor"
          "resolved": str           # resolved path that did not exist (repo-relative)
        }
      ],
      "unlinked_resources": [       # one entry per discovered resource with no README link
        {
          "kind": str,              # resource kind, e.g. "skills" or "agents"
          "name": str,              # resource name
          "path": str               # repo-relative source path the README must link
        }
      ]
    }
"""

import argparse
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


def _display(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def scan_links(registry: list[dict]) -> tuple[list[dict], dict[str, int]]:
    broken: list[dict] = []
    counts = {"markdown_scanned": 0, "vendored_skipped": 0, "links_resolved": 0}
    for md in tracked_markdown():
        if is_vendored(md, registry):
            counts["vendored_skipped"] += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        counts["markdown_scanned"] += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                resolved = (md.parent / bare).resolve()
                if resolved.exists():
                    counts["links_resolved"] += 1
                else:
                    broken.append(
                        {
                            "file": md.relative_to(ROOT).as_posix(),
                            "line": line_no,
                            "target": target,
                            "resolved": _display(resolved),
                        }
                    )
    return broken, counts


def find_unlinked() -> tuple[list[dict], int]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    unlinked = []
    for item in items:
        path = item.src.relative_to(ROOT).as_posix()
        if f"]({path})" not in readme:
            unlinked.append({"kind": item.kind, "name": item.name, "path": path})
    return unlinked, len(items)


def check_links(registry: list[dict]) -> list[str]:
    broken, _ = scan_links(registry)
    return [f"{Path(b['file'])}:{b['line']}: broken-link -> {b['target']}" for b in broken]


def check_readme_coverage() -> list[str]:
    unlinked, _ = find_unlinked()
    return [
        f"README.md: undocumented -> {u['kind']}/{u['name']} (add a row linking {u['path']})"
        for u in unlinked
    ]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit one machine-readable JSON object on stdout instead of the report",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    if args.json:
        broken, counts = scan_links(registry)
        unlinked, resources_checked = find_unlinked()
        report = {
            "pass": not (broken or unlinked),
            "counts": {**counts, "resources_checked": resources_checked},
            "broken_links": broken,
            "unlinked_resources": unlinked,
        }
        print(json.dumps(report, indent=2))
        finding_count = len(broken) + len(unlinked)
    else:
        findings = check_links(registry) + check_readme_coverage()
        for finding in findings:
            print(finding)
        finding_count = len(findings)
    if finding_count:
        print(f"\n{finding_count} finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
