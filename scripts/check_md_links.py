#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

The script can output in two modes:
- Default: human-readable format, one finding per line.
- --json: machine-readable JSON object with the following shape:

{
    "passed": boolean,  # True if no findings, False otherwise
    "markdown_files_scanned": integer,  # number of markdown files considered (from git ls-files)
    "links_resolved": integer,  # number of links checked (after skipping certain
                                 prefixes and empty anchors)
    "files_skipped_vendored": integer,  # number of markdown files skipped because
                                        they are vendored
    "resources_checked": integer,  # number of resources discovered by
                                   claude_all.cli.discover
    "broken_links": [  # list of objects for each broken link
        {
            "file": string,  # path of the markdown file containing the broken
                             link, relative to repo root
            "line": integer,  # line number in the markdown file (1-indexed)
            "target": string,  # the raw link target as found in the markdown
            "resolved_path": string  # the resolved path that was checked and did
                                     not exist; if the resolved path is inside the
                                     repo, it is relative to the repo root;
                                     otherwise, it is an absolute path
        }
    ],
    "unlinked_resources": [  # list of objects for each resource not found in
                             the README
        {
            "path": string,  # path of the resource relative to the repo root
            "kind": string,  # the kind of the resource (e.g., "skill", "agent")
            "name": string   # the name of the resource
        }
    ]
}

Exit codes are the same in both modes: 0 if no findings, 1 otherwise.
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


def check_links(registry: list[dict]) -> tuple[list[dict], dict]:
    findings = []  # will be list of dicts
    stats = {"markdown_files_scanned": 0, "links_resolved": 0, "files_skipped_vendored": 0}
    markdown_files = tracked_markdown()
    stats["markdown_files_scanned"] = len(markdown_files)
    for md in markdown_files:
        if is_vendored(md, registry):
            stats["files_skipped_vendored"] += 1
            continue
        if not md.exists():
            continue
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                stats["links_resolved"] += 1
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    resolved_abs = (md.parent / bare).resolve()
                    if resolved_abs.is_relative_to(ROOT):
                        resolved_str = resolved_abs.relative_to(ROOT).as_posix()
                    else:
                        resolved_str = resolved_abs.as_posix()
                    findings.append(
                        {
                            "file": rel.as_posix(),
                            "line": line_no,
                            "target": target,
                            "resolved_path": resolved_str,
                        }
                    )
    return findings, stats


def check_readme_coverage() -> tuple[list[dict], dict]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    findings = []
    for item in items:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            findings.append(
                {
                    "path": item.src.relative_to(ROOT).as_posix(),
                    "kind": item.kind,
                    "name": item.name,
                }
            )
    stats = {"resources_checked": len(items)}
    return findings, stats


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--json", action="store_true")
    args, unknown = parser.parse_known_args()
    if unknown:
        # Ignore unknown arguments for backward compatibility
        pass

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    link_findings, link_stats = check_links(registry)
    coverage_findings, coverage_stats = check_readme_coverage()

    total_findings = len(link_findings) + len(coverage_findings)
    exit_code = 0 if total_findings == 0 else 1

    if args.json:
        result = {
            "passed": exit_code == 0,
            "markdown_files_scanned": link_stats["markdown_files_scanned"],
            "links_resolved": link_stats["links_resolved"],
            "files_skipped_vendored": link_stats["files_skipped_vendored"],
            "resources_checked": coverage_stats["resources_checked"],
            "broken_links": link_findings,
            "unlinked_resources": coverage_findings,
        }
        print(json.dumps(result))
        return exit_code
    else:
        # Output human-readable format
        for finding in link_findings:
            print(f"{finding['file']}:{finding['line']}: broken-link -> {finding['target']}")
        for finding in coverage_findings:
            print(
                f"README.md: undocumented -> {finding['kind']}/{finding['name']} "
                f"(add a row linking {finding['path']})"
            )
        if total_findings > 0:
            print(f"\n{total_findings} finding(s).", file=sys.stderr)
        return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
