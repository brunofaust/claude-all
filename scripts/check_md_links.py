#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

The script defaults to human-readable output. With `--json`, it emits a machine-readable
JSON object to stdout instead, containing:

{
    "pass_fail": bool,                    # True if no findings, False otherwise
    "counts": {
        "markdown_files_scanned": int,    # Number of Markdown files examined (vendored skipped)
        "links_resolved": int,            # Number of relative Markdown links checked
        "resources_checked": int,         # Number of resources discovered via `claude-all discover`
        "files_skipped_as_vendored": int  # Number of Markdown files skipped due to vendored exemption
    },
    "broken_links": [                     # Each unresolved relative link
        {
            "file": str,                  # Path of Markdown file containing the link, relative to repo root
            "line": int,                  # Line number (1-indexed) of the link
            "raw_target": str,            # The link target as written in the Markdown
            "resolved_path": str          # The absolute path that was checked and did not exist
        }
    ],
    "unlinked_resources": [               # Each resource not linked from README
        {
            "kind": str,                  # Kind of resource (e.g., "skill", "agent")
            "name": str,                  # Name of resource
            "path": str                   # Path to resource's source file, relative to repo root
        }
    ]
}

Diagnostics (e.g., findings count) are printed to stderr in both modes.
Exit codes are identical in both modes for the same input.
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
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    findings.append(f"{rel}:{line_no}: broken-link -> {target}")
    return findings


def check_links_json(registry: list[dict]) -> tuple[int, int, int, list[dict]]:
    """Return (markdown_files_scanned, links_resolved, files_skipped_as_vendored, broken_links_list)"""
    markdown_files_scanned = 0
    links_resolved = 0
    files_skipped_as_vendored = 0
    broken_links = []

    for md in tracked_markdown():
        if is_vendored(md, registry):
            files_skipped_as_vendored += 1
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
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    broken_links.append(
                        {
                            "file": str(rel),
                            "line": line_no,
                            "raw_target": target,
                            "resolved_path": str((md.parent / bare).resolve()),
                        }
                    )
    return markdown_files_scanned, links_resolved, files_skipped_as_vendored, broken_links


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


def check_readme_coverage_json() -> tuple[int, list[dict]]:
    """Return (resources_checked, unlinked_resources_list)"""
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = list(discover([]))
    resources_checked = len(items)
    unlinked_resources = []

    for item in items:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            unlinked_resources.append(
                {
                    "kind": item.kind,
                    "name": item.name,
                    "path": item.src.relative_to(ROOT).as_posix(),
                }
            )

    return resources_checked, unlinked_resources


def check_all_json(registry: list[dict]) -> dict:
    """Return JSON-serializable dict with all check results."""
    markdown_files_scanned, links_resolved, files_skipped_as_vendored, broken_links = (
        check_links_json(registry)
    )
    resources_checked, unlinked_resources = check_readme_coverage_json()

    pass_fail = len(broken_links) == 0 and len(unlinked_resources) == 0

    return {
        "pass_fail": pass_fail,
        "counts": {
            "markdown_files_scanned": markdown_files_scanned,
            "links_resolved": links_resolved,
            "resources_checked": resources_checked,
            "files_skipped_as_vendored": files_skipped_as_vendored,
        },
        "broken_links": broken_links,
        "unlinked_resources": unlinked_resources,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Check markdown links and README coverage")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    if args.json:
        result = check_all_json(registry)
        print(json.dumps(result))
        # Print findings count to stderr for compatibility
        findings_count = len(result["broken_links"]) + len(result["unlinked_resources"])
        if findings_count:
            print(f"\n{findings_count} finding(s).", file=sys.stderr)
        return 0 if result["pass_fail"] else 1
    else:
        findings = check_links(registry) + check_readme_coverage()
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
