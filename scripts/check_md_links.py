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

The script supports an optional --json flag for machine-readable output.

When --json is passed, stdout contains a single JSON object with the following shape:

{
  "passed": <bool>,
  "counts": {
    "markdown_files_scanned": <int>,
    "links_resolved": <int>,
    "resources_checked": <int>,
    "files_skipped_as_vendored": <int>
  },
  "broken_links": [
    {"file": "<relative path>", "target": "<raw link target>", "resolved_path": "<relative path>"}
  ],
  "unlinked_resources": ["<relative path>", ...]
}

* passed is True when no broken links and no unlinked resources are found.
* markdown_files_scanned is the number of non-vendored markdown files that exist and were scanned.
* links_resolved is the number of link targets examined after filtering images, URLs, and anchors.
* resources_checked is the total number of resources discovered via claude_all.cli.discover.
* files_skipped_as_vendored is the number of tracked markdown files exempted by vendored rules.
* broken_links entries report containing file, raw target, and resolved path that did not exist.
* unlinked_resources lists relative repo-root paths of resources not referenced from README.md.
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


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--json", action="store_true")
    args, _ = parser.parse_known_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    if args.json:
        tracked = tracked_markdown()
        files_skipped_as_vendored = sum(1 for md in tracked if is_vendored(md, registry))

        markdown_files_scanned = 0
        links_resolved = 0

        # Count scanned files and examined links using the same stripping logic as check_links
        for md in tracked:
            if is_vendored(md, registry):
                continue
            if not md.exists():
                continue
            markdown_files_scanned += 1
            try:
                text = md.read_text()
            except Exception:
                continue
            for _, line in strip_code_blocks(text):
                cleaned = CODE_SPAN.sub("", line)
                for target in LINK.findall(cleaned):
                    if target.startswith(SKIP_PREFIX):
                        continue
                    bare = target.split("#", 1)[0]
                    if not bare:
                        continue
                    links_resolved += 1

        # Use existing validation to avoid re-implementing checks
        broken_findings = check_links(registry)
        broken_links = []
        broken_re = re.compile(r"^(?P<file>.+?):(?P<line>\d+): broken-link -> (?P<target>.+)$")
        for finding in broken_findings:
            m = broken_re.match(finding)
            if not m:
                continue
            file_rel = m.group("file")
            target = m.group("target")
            md_path = ROOT / file_rel
            bare = target.split("#", 1)[0]
            candidate = md_path.parent / bare
            try:
                resolved_abs = candidate.resolve()
            except Exception:
                resolved_abs = candidate
            try:
                resolved_rel = resolved_abs.relative_to(ROOT.resolve())
                resolved_path = resolved_rel.as_posix()
            except ValueError:
                resolved_path = resolved_abs.as_posix()
            broken_links.append(
                {
                    "file": file_rel,
                    "target": target,
                    "resolved_path": resolved_path,
                }
            )

        sys.path.insert(0, str(ROOT / "src"))
        from claude_all.cli import discover

        items = list(discover([]))
        resources_checked = len(items)

        readme_findings = check_readme_coverage()
        unlinked_resources = []
        unlinked_re = re.compile(r"add a row linking (?P<path>.+)\)")
        for finding in readme_findings:
            m = unlinked_re.search(finding)
            if m:
                unlinked_resources.append(m.group("path"))

        passed = not broken_links and not unlinked_resources
        output = {
            "passed": passed,
            "counts": {
                "markdown_files_scanned": markdown_files_scanned,
                "links_resolved": links_resolved,
                "resources_checked": resources_checked,
                "files_skipped_as_vendored": files_skipped_as_vendored,
            },
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }
        json.dump(output, sys.stdout)
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
