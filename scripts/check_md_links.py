#!/usr/bin/env python3
"""Gate: relative markdown links resolve, and every resource is linked from the README.

Two failures this repo has actually shipped, now mechanical:

1. **Broken relative links.** Four cross-skill links went out one `../` short —
   one of them in an already-merged PR — because nothing checked them. A link is
   only as good as the last rename.
2. **A resource with no README row.** CLAUDE.md says "a PR without a README update
   is incomplete", but prose does not enforce itself. The README tables link to
   each resource's source file, so "is it linked?" is a proxy for "is it documented?"
   that a checker can actually answer.

Vendored files are exempt from check 1: they are kept byte-identical to upstream,
so their upstream-relative links legitimately do not resolve in this tree. Files
listed under a vendored entry's `local_only` are OURS and stay checked.

JSON output (--json)

When invoked with --json, the script emits a single JSON object to stdout instead
of the human report. The shape is stable:

{
  "passed": bool,
  "markdown_files_scanned": int,
  "links_checked": int,
  "resources_checked": int,
  "files_skipped_as_vendored": int,
  "broken_links": [
    {"file": "path/to/file.md", "target": "relative/path.md", "resolved_path": "path/to/resolved"}
  ],
  "unlinked_resources": ["path/to/src/file.md", ...]
}

* passed is overall pass/fail
* markdown_files_scanned is the number of non-vendored markdown files inspected
* links_checked is the total number of link targets examined after filtering
* resources_checked is the number of resources discovered via claude_all.cli.discover
* files_skipped_as_vendored is the number of tracked markdown files exempted by vendored logic
* broken_links entries contain file, target, and resolved path that did not exist
* unlinked_resources is a list of source file paths relative to repo root with no README row
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
    """Upstream-owned files are exempt: kept byte-identical, so their own relative
    links point at an upstream tree we deliberately did not copy. `local_only`
    files live in the same directory but are OURS — they stay checked.

    Args:
        path: The markdown file being considered.
        registry: The `vendored` entries from `vendored.json`.
    """
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
    """Numbered lines with fenced code removed — a regex or an llms.txt sample
    inside a fenced block only looks like a link.

    Args:
        text: Full markdown source of one file.
    """
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


def _collect_link_info(registry: list[dict]):
    markdown_files = tracked_markdown()
    files_skipped = 0
    files_scanned = 0
    links_checked = 0
    broken_links = []
    for md in markdown_files:
        if is_vendored(md, registry):
            files_skipped += 1
            continue
        if not md.exists():
            continue
        files_scanned += 1
        for _line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue
                links_checked += 1
                candidate = (md.parent / bare).resolve()
                if not candidate.exists():
                    rel = md.relative_to(ROOT)
                    try:
                        resolved_path = candidate.relative_to(ROOT).as_posix()
                    except ValueError:
                        resolved_path = str(candidate)
                    broken_links.append(
                        {
                            "file": rel.as_posix(),
                            "target": target,
                            "resolved_path": resolved_path,
                        }
                    )
    return files_scanned, files_skipped, links_checked, broken_links


def _collect_readme_info():
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    resources_checked = len(items)
    unlinked_resources = []
    for item in items:
        rel_path = item.src.relative_to(ROOT).as_posix()
        if f"]({rel_path})" not in readme:
            unlinked_resources.append(rel_path)
    return resources_checked, unlinked_resources


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--json", action="store_true")
    args, _ = parser.parse_known_args()
    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    if args.json:
        files_scanned, files_skipped, links_checked, broken_links = _collect_link_info(registry)
        resources_checked, unlinked_resources = _collect_readme_info()
        passed = not broken_links and not unlinked_resources
        output = {
            "passed": passed,
            "markdown_files_scanned": files_scanned,
            "links_checked": links_checked,
            "resources_checked": resources_checked,
            "files_skipped_as_vendored": files_skipped,
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }
        print(json.dumps(output))
        return 0 if passed else 1
    findings = check_links(registry) + check_readme_coverage()
    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
