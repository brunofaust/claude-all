#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With --json, output a machine-readable object with:
- passed: boolean indicating if all checks pass
- counts: dict with keys:
    - markdown_files_scanned: number of markdown files processed (excluding vendored and missing)
    - links_resolved: number of links examined in those files
    - resources_checked: number of resources discovered by claude_all.cli.discover
    - files_skipped_as_vendored: number of markdown files skipped due to vendored exemption
- broken_links: list of objects, each with:
    - file: relative path of the markdown file containing the broken link
    - target: the raw link target as found in the markdown
    - resolved_path: the absolute path that was checked and did not exist
- unlinked_resources: list of objects, each with:
    - path: relative path of the resource (skill, agent, etc.) that is not linked in the README
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


def check_links_structured(registry: list[dict]) -> tuple[list[dict], int, int, int]:
    """Return (broken_links, files_scanned, links_resolved, files_skipped_vendored)
    where each broken_link is a dict with keys:
    file (str, relative to root), line (int), target (str), resolved_path (str, absolute)
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
                    rel = md.relative_to(ROOT)
                    broken_links.append(
                        {
                            "file": str(rel),
                            "line": line_no,
                            "target": target,
                            "resolved_path": str((md.parent / bare).resolve()),
                        }
                    )
    return broken_links, files_scanned, links_resolved, files_skipped_vendored


def check_readme_coverage_structured() -> tuple[list[dict], int]:
    """Return (unlinked_resources, resources_checked)
    where each unlinked_resource is a dict with key: path (str, relative to root)
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    resources = discover([])
    resources_checked = len(resources)
    unlinked_resources = []
    for item in resources:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            unlinked_resources.append({"path": item.src.relative_to(ROOT).as_posix()})
    return unlinked_resources, resources_checked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    if args.json:
        broken_links, files_scanned, links_resolved, files_skipped_vendored = (
            check_links_structured(registry)
        )
        unlinked_resources, resources_checked = check_readme_coverage_structured()

        total_findings = len(broken_links) + len(unlinked_resources)
        passed = total_findings == 0

        result = {
            "passed": passed,
            "counts": {
                "markdown_files_scanned": files_scanned,
                "links_resolved": links_resolved,
                "resources_checked": resources_checked,
                "files_skipped_as_vendored": files_skipped_vendored,
            },
            "broken_links": [
                {"file": bl["file"], "target": bl["target"], "resolved_path": bl["resolved_path"]}
                for bl in broken_links
            ],
            "unlinked_resources": [{"path": ur["path"]} for ur in unlinked_resources],
        }
        print(json.dumps(result))
        return 0 if passed else 1
    else:
        # Existing behavior
        findings = check_links(registry) + check_readme_coverage()
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
