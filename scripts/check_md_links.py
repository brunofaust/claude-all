#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With --json flag, emits machine-readable JSON to stdout instead of human-readable
findings. JSON includes: passed, markdown_files_scanned, links_resolved,
vendored_files_skipped, resources_checked, broken_links[], unlinked_resources[].
Diagnostics to stderr in both modes. Exit codes identical in both modes.
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


def check_links_json(registry: list[dict]) -> tuple[list[dict], int, int, int]:
    """Check links for JSON output.

    Returns (broken_links, markdown_files_scanned, links_resolved, vendored_files_skipped).
    """
    broken_links = []
    markdown_files_scanned = 0
    links_resolved = 0
    vendored_files_skipped = 0

    for md in tracked_markdown():
        if is_vendored(md, registry):
            vendored_files_skipped += 1
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
                    resolved_path = (md.parent / bare).relative_to(ROOT)
                    broken_links.append(
                        {
                            "file": str(rel),
                            "line": line_no,
                            "target": target,
                            "resolved_path": str(resolved_path),
                        }
                    )
    return broken_links, markdown_files_scanned, links_resolved, vendored_files_skipped


def check_readme_coverage_json() -> tuple[list[dict], int]:
    """Check README coverage for JSON output.

    Returns (unlinked_resources, resources_checked).
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = list(discover([]))
    resources_checked = len(items)
    unlinked_resources = []

    for item in items:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            unlinked_resources.append(
                {"file": str(item.src.relative_to(ROOT)), "kind": item.kind, "name": item.name}
            )
    return unlinked_resources, resources_checked


def main() -> int:
    parser = argparse.ArgumentParser(description="Check markdown links and README coverage")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    if args.json:
        # JSON mode
        broken_links, markdown_files_scanned, links_resolved, vendored_files_skipped = (
            check_links_json(registry)
        )
        unlinked_resources, resources_checked = check_readme_coverage_json()

        passed = len(broken_links) == 0 and len(unlinked_resources) == 0

        result = {
            "passed": passed,
            "markdown_files_scanned": markdown_files_scanned,
            "links_resolved": links_resolved,
            "vendored_files_skipped": vendored_files_skipped,
            "resources_checked": resources_checked,
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }

        print(json.dumps(result))
        if not passed:
            total_findings = len(broken_links) + len(unlinked_resources)
            print(f"\n{total_findings} finding(s).", file=sys.stderr)
        return 0 if passed else 1
    else:
        # Human-readable mode (existing behavior)
        findings = check_links(registry) + check_readme_coverage()
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
