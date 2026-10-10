#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With --json flag, emits a machine-readable JSON object to stdout instead of the
human-readable report. The JSON shape is:

{
    "passed": bool,  # True if no broken links and all resources are linked
    "markdown_files_scanned": int,  # number of Markdown files inspected for links
    "links_resolved": int,  # number of link targets inspected (after skipping
                            # images, absolute URLs, anchors, mailto, etc.)
    "resources_checked": int,  # number of items discovered via claude_all.cli.discover
    "files_skipped_as_vendored": int,  # number of Markdown files skipped due to
                                       # vendored exemption
    "broken_links": [  # list of objects for each broken link
        {
            "file": str,  # path of Markdown file containing the link, relative to repo root
            "line": int,  # line number (1-based) of the link
            "target": str,  # raw link target as found in the Markdown
            "resolved": str  # absolute path that was checked and did not exist
        }
    ],
    "unlinked_resources": [  # list of objects for each resource not linked from README
        {
            "path": str,  # path of the resource's source file, relative to repo root
            "kind": str,  # kind of resource (e.g., "skill", "agent")
            "name": str   # name of resource
        }
    ]
}

Without --json, output and exit codes are unchanged from the original behavior.
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


def check_links(
    registry: list[dict],
) -> tuple[
    list[dict],  # broken links structured
    int,  # markdown files scanned
    int,  # links resolved
    int,  # files skipped as vendored
]:
    broken_links = []
    md_scanned = 0
    links_resolved = 0
    vendored_skipped = 0
    for md in tracked_markdown():
        if is_vendored(md, registry):
            vendored_skipped += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        md_scanned += 1
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
                            "target": target,
                            "resolved": str((md.parent / bare).resolve()),
                        }
                    )
    return broken_links, md_scanned, links_resolved, vendored_skipped


def check_readme_coverage() -> tuple[
    list[dict],  # unlinked resources structured
    int,  # resources checked
]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    unlinked = []
    for item in items:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            unlinked.append(
                {
                    "path": str(item.src.relative_to(ROOT).as_posix()),
                    "kind": item.kind,
                    "name": item.name,
                }
            )
    return unlinked, len(items)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    broken_links, md_scanned, links_resolved, vendored_skipped = check_links(registry)
    unlinked_resources, resources_checked = check_readme_coverage()

    if args.json:
        passed = len(broken_links) == 0 and len(unlinked_resources) == 0
        data = {
            "passed": passed,
            "markdown_files_scanned": md_scanned,
            "links_resolved": links_resolved,
            "resources_checked": resources_checked,
            "files_skipped_as_vendored": vendored_skipped,
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }
        print(json.dumps(data))
        return 0 if passed else 1
    else:
        findings = []
        for bl in broken_links:
            findings.append(f"{bl['file']}:{bl['line']}: broken-link -> {bl['target']}")
        for ul in unlinked_resources:
            findings.append(
                f"README.md: undocumented -> {ul['kind']}/{ul['name']} "
                f"(add a row linking {ul['path']})"
            )
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
