#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With --json flag, emits a machine-readable JSON object instead of human-readable
findings. The JSON structure is:
{
  "passed": boolean,
  "counts": {
    "markdown_files_scanned": int,
    "links_resolved": int,
    "resources_checked": int,
    "files_skipped_as_vendored": int
  },
  "broken_links": [
    {
      "file": string,  # path relative to repo root
      "line": int,     # line number in the file
      "target": string,  # raw link target from markdown
      "resolved_path": string  # path that was checked and did not exist
    }
  ],
  "unlinked_resources": [
    {
      "kind": string,
      "name": string,
      "path": string  # path relative to repo root
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


def check_links_structured(registry: list[dict]) -> tuple[list[dict], dict]:
    """Check markdown links, returning structured data and counts.

    Returns:
        tuple of (broken_links_list, counts_dict)
        broken_links_list: list of dicts with keys file, line, target, resolved_path
        counts_dict: dict with keys markdown_files_scanned, links_resolved
    """
    broken_links = []
    counts = {
        "markdown_files_scanned": 0,
        "links_resolved": 0,
    }
    for md in tracked_markdown():
        if is_vendored(md, registry):
            counts["files_skipped_as_vendored"] = counts.get("files_skipped_as_vendored", 0) + 1
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
                    resolved_path = (md.parent / bare).resolve()
                    try:
                        resolved_path_str = resolved_path.relative_to(ROOT).as_posix()
                    except ValueError:
                        # If resolved path is outside repo, make it absolute
                        resolved_path_str = resolved_path.as_posix()
                    broken_links.append(
                        {
                            "file": rel.as_posix(),
                            "line": line_no,
                            "target": target,
                            "resolved_path": resolved_path_str,
                        }
                    )
    return broken_links, counts


def check_readme_coverage_structured() -> tuple[list[dict], int]:
    """Check README coverage, returning structured data and count.

    Returns:
        tuple of (unlinked_resources_list, resources_checked_count)
        unlinked_resources_list: list of dicts with keys kind, name, path
        resources_checked_count: total number of resources discovered
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
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

    return unlinked_resources, len(items)


def main() -> int:

    parser = argparse.ArgumentParser(description="Check markdown links and README coverage")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable output",
    )
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    broken_links, link_counts = check_links_structured(registry)
    unlinked_resources, resources_checked = check_readme_coverage_structured()

    # Combine counts
    counts = {
        "markdown_files_scanned": link_counts["markdown_files_scanned"],
        "links_resolved": link_counts["links_resolved"],
        "resources_checked": resources_checked,
        "files_skipped_as_vendored": link_counts.get("files_skipped_as_vendored", 0),
    }

    findings = broken_links + unlinked_resources  # For exit code determination
    passed = len(findings) == 0

    if args.json:
        output = {
            "passed": passed,
            "counts": counts,
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }
        print(json.dumps(output, indent=None))  # Compact JSON as requested
    else:
        # Human-readable output (preserve existing behavior)
        for md in tracked_markdown():
            if is_vendored(md, registry):
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
                    if not (md.parent / bare).resolve().exists():
                        rel = md.relative_to(ROOT)
                        print(f"{rel}:{line_no}: broken-link -> {target}")

        for item in unlinked_resources:
            print(
                f"README.md: undocumented -> {item['kind']}/{item['name']} "
                f"(add a row linking {item['path']})"
            )

    if findings:
        print(f"\n{len(findings)} finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
