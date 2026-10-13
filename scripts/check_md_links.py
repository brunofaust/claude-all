#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt; their local_only sidecars are checked.
README links are the proxy for "documented".

With --json, output JSON: pass/fail, counts, broken links, unlinked resources.
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


def check_links_internal(registry: list[dict], counts: dict) -> list[dict]:
    broken_links = []
    for md in tracked_markdown():
        if is_vendored(md, registry):
            counts["vendored_skipped"] += 1
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
                counts["links_checked"] += 1
                if not (md.parent / bare).resolve().exists():
                    broken_links.append({"md_file": md, "line_no": line_no, "target": target})
    return broken_links


def check_readme_coverage_internal(counts: dict) -> list[dict]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    unlinked_resources = []
    for item in discover([]):
        counts["resources_checked"] += 1
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            unlinked_resources.append({"item": item})
    return unlinked_resources


def format_broken_link_finding(finding: dict) -> str:
    rel_path = finding["md_file"].relative_to(ROOT).as_posix()
    return f"{rel_path}:{finding['line_no']}: broken-link -> {finding['target']}"


def format_unlinked_resource_finding(finding: dict) -> str:
    item = finding["item"]
    return (
        f"README.md: undocumented -> {item.kind}/{item.name} "
        f"(add a row linking {item.src.relative_to(ROOT).as_posix()})"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    counts = {
        "markdown_files_scanned": 0,
        "links_checked": 0,
        "vendored_skipped": 0,
        "resources_checked": 0,
    }
    broken_links_struct = check_links_internal(registry, counts)
    unlinked_resources_struct = check_readme_coverage_internal(counts)

    if args.json:
        # Build JSON object
        passed = len(broken_links_struct) == 0 and len(unlinked_resources_struct) == 0
        # Format broken links for JSON
        json_broken_links = []
        for bl in broken_links_struct:
            md_file = bl["md_file"]
            target = bl["target"]
            bare = target.split("#", 1)[0]
            resolved_path = (md_file.parent / bare).resolve()
            try:
                rel_resolved = resolved_path.relative_to(ROOT)
                resolved_str = rel_resolved.as_posix()
            except ValueError:
                resolved_str = resolved_path.as_posix()
            json_broken_links.append(
                {
                    "file": md_file.relative_to(ROOT).as_posix(),
                    "link": target,
                    "resolved_path": resolved_str,
                }
            )
        # Format unlinked resources for JSON: just the relative path string
        json_unlinked_resources = [
            item["item"].src.relative_to(ROOT).as_posix() for item in unlinked_resources_struct
        ]
        result = {
            "passed": passed,
            "counts": counts,
            "broken_links": json_broken_links,
            "unlinked_resources": json_unlinked_resources,
        }
        print(json.dumps(result, indent=2))
        return 0 if passed else 1
    else:
        # Non-JSON mode: format findings as strings and print
        all_findings = []
        for bl in broken_links_struct:
            all_findings.append(format_broken_link_finding(bl))
        for ur in unlinked_resources_struct:
            all_findings.append(format_unlinked_resource_finding(ur))
        for finding in all_findings:
            print(finding)
        if all_findings:
            print(f"\n{len(all_findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
