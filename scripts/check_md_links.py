#!/usr/bin/env python3
"""Gate: relative Markdown links resolve and every resource is linked from the README.

Vendored files are exempt; `local_only` sidecars remain checked. README links
proxy for documentation. `--json` emits `passed`, `counts` (`markdown_files_scanned`,
`links_resolved`, `resources_checked`, `vendored_files_skipped`), `broken_links`
(each with `file`, `target`, `resolved_path`), and `unlinked_resources` (paths).
Missing tracked files are not scanned.
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


def check_links(registry: list[dict]) -> tuple[list[str], list[dict], dict[str, int]]:
    findings = []
    broken_links = []
    counts = {"markdown_files_scanned": 0, "links_resolved": 0, "vendored_files_skipped": 0}
    for md in tracked_markdown():
        if is_vendored(md, registry):
            counts["vendored_files_skipped"] += 1
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
                resolved = (md.parent / bare).resolve()
                if not resolved.exists():
                    rel = md.relative_to(ROOT)
                    findings.append(f"{rel}:{line_no}: broken-link -> {target}")
                    broken_links.append(
                        {
                            "file": rel.as_posix(),
                            "target": target,
                            "resolved_path": resolved.relative_to(ROOT).as_posix()
                            if resolved.is_relative_to(ROOT)
                            else str(resolved),
                        }
                    )
                else:
                    counts["links_resolved"] += 1
    return findings, broken_links, counts


def check_readme_coverage() -> tuple[list[str], list[str], int]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    resources = discover([])
    unlinked = [
        item for item in resources if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme
    ]
    findings = [
        f"README.md: undocumented -> {item.kind}/{item.name} "
        f"(add a row linking {item.src.relative_to(ROOT).as_posix()})"
        for item in unlinked
    ]
    return findings, [item.src.relative_to(ROOT).as_posix() for item in unlinked], len(resources)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    args = parser.parse_args()
    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    link_findings, broken_links, counts = check_links(registry)
    coverage_findings, unlinked_resources, resources_checked = check_readme_coverage()
    findings = link_findings + coverage_findings
    counts["resources_checked"] = resources_checked
    if args.json:
        print(
            json.dumps(
                {
                    "passed": not findings,
                    "counts": counts,
                    "broken_links": broken_links,
                    "unlinked_resources": unlinked_resources,
                }
            )
        )
    else:
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
