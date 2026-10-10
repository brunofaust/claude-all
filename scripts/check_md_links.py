#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

JSON output mode:
    --json: emit a single JSON object to stdout with the following shape:
    {
        "pass": bool,  # True if no broken links and no unlinked resources
        "counts": {
            "markdown_files_scanned": int,
            "links_resolved": int,
            "resources_checked": int,
            "files_skipped_as_vendored": int
        },
        "broken_links": [
            {
                "file": str,  # relative path of markdown file
                "line": int,  # line number (1-indexed)
                "raw_target": str,  # the link target as found in markdown
                "resolved_path": str,  # the absolute path that was checked and did not exist
            }
        ],
        "unlinked_resources": [
            {
                "resource": str,  # relative path of resource file from repo root
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


def check_links(registry: list[dict]):
    """Return (broken_links, files_scanned, links_resolved, files_skipped_vendored) where:
    - broken_links: list of dicts with keys: file, line, raw_target, resolved_path
    - files_scanned: number of markdown files processed (after vendored filter and existence check)
    - links_resolved: number of links considered (after skipping known prefixes and empty anchors)
    - files_skipped_vendored: number of markdown files skipped due to being vendored
    """
    broken_links = []
    files_scanned = 0
    links_resolved = 0
    files_skipped_vendored = 0
    for md in tracked_markdown():
        if is_vendored(md, registry):
            files_skipped_vendored += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        files_scanned += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                links_resolved += 1
                if not (md.parent / bare).resolve().exists():
                    rel_md = md.relative_to(ROOT)
                    resolved = (md.parent / bare).resolve()
                    # Try to make resolved path relative to ROOT if possible
                    try:
                        resolved_rel = resolved.relative_to(ROOT)
                        resolved_str = str(resolved_rel)
                    except ValueError:
                        resolved_str = str(resolved)
                    broken_links.append(
                        {
                            "file": str(rel_md),
                            "line": line_no,
                            "raw_target": target,
                            "resolved_path": resolved_str,
                        }
                    )
    return broken_links, files_scanned, links_resolved, files_skipped_vendored


def check_readme_coverage():
    """Return (unlinked_resources, resources_checked) where:
    - unlinked_resources: list of dicts with key: resource (relative path of resource's SKILL.md)
    - resources_checked: number of resources discovered
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    unlinked = []
    for item in items:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            unlinked.append({"resource": str(item.src.relative_to(ROOT))})
    return unlinked, len(items)


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check markdown links and README coverage.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable text.",
    )
    parsed_args = parser.parse_args() if args is None else parser.parse_args(args)

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    broken_links, files_scanned, links_resolved, files_skipped_vendored = check_links(registry)
    unlinked_resources, resources_checked = check_readme_coverage()
    findings_exist = bool(broken_links or unlinked_resources)
    exit_code = 1 if findings_exist else 0

    if parsed_args.json:
        output = {
            "pass": not findings_exist,
            "counts": {
                "markdown_files_scanned": files_scanned,
                "links_resolved": links_resolved,
                "resources_checked": resources_checked,
                "files_skipped_as_vendored": files_skipped_vendored,
            },
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }
        print(json.dumps(output))
    else:
        # Human-readable output (preserve existing format)
        for bl in broken_links:
            print(f"{bl['file']}:{bl['line']}: broken-link -> {bl['raw_target']}")
        for ur in unlinked_resources:
            # Reconstruct the original message:
            # "README.md: undocumented -> {resource} (add a row linking {resource})"
            print(
                f"README.md: undocumented -> {ur['resource']} (add a row linking {ur['resource']})"
            )
        if findings_exist:
            total_findings = len(broken_links) + len(unlinked_resources)
            print(f"\n{total_findings} finding(s).", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
