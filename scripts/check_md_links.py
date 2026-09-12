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

The script can emit a machine-readable JSON report when invoked with `--json`.
In JSON mode, the output is a single JSON object containing:
- `pass`: boolean indicating overall success
- `markdown_files_scanned`: number of non-vendored Markdown files scanned for links
- `links_resolved`: number of link targets checked for existence
- `resources_checked`: number of resources discovered and checked for README presence
- `files_skipped_as_vendored`: number of Vendored Markdown files skipped
- `broken_links`: list of objects, each with:
    - `file`: Markdown file containing the broken link (relative to repository root)
    - `raw_link_target`: link target as found in the source (including fragment, if any)
    - `resolved_path`: absolute path that was checked and did not exist
- `unlinked_resources`: list of resource paths (relative to repository root) that are
  not linked from the README

Without `--json`, the script emits the human-readable report line by line to stdout
and a summary to stderr, exactly as before.
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


def check_links(registry: list[dict]):
    """Check Markdown files for broken relative links.

    Returns a tuple (broken_links_info, files_scanned, links_checked, files_skipped_vendored)
    where:
        broken_links_info: list of dicts, each with keys:
            - file_rel: Path relative to ROOT of the Markdown file
            - line_no: line number in that file (1-indexed)
            - raw_target: the raw link target as found in the source
            - resolved_path: absolute Path that was checked and did not exist
        files_scanned: number of non-vendored Markdown files scanned
        links_checked: number of link targets checked for existence
        files_skipped_vendored: number of Vendored Markdown files skipped
    """
    findings = []
    files_scanned = 0
    links_checked = 0
    files_skipped_vendored = 0
    for md in tracked_markdown():
        if is_vendored(md, registry):
            files_skipped_vendored += 1
            continue
        files_scanned += 1
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
                links_checked += 1
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    findings.append(
                        {
                            "file_rel": rel,
                            "line_no": line_no,
                            "raw_target": target,
                            "resolved_path": (md.parent / bare).resolve(),
                        }
                    )
    return findings, files_scanned, links_checked, files_skipped_vendored


def check_readme_coverage():
    """Check that every discovered resource is linked from the README.

    Returns a tuple (unlinked_info, resources_checked) where:
        unlinked_info: list of dicts, each with keys:
            - kind: resource kind (e.g., "skill", "agent")
            - name: resource name
            - path_rel: Path to the resource's source file relative to ROOT
        resources_checked: number of resources discovered and checked
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    resources = discover([])
    resources_checked = len(resources)
    findings = []
    for item in resources:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            findings.append(
                {
                    "kind": item.kind,
                    "name": item.name,
                    "path_rel": item.src.relative_to(ROOT),
                }
            )
    return findings, resources_checked


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Markdown links and README coverage.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON report instead of human-readable text",
    )
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    links_info, files_scanned, links_checked, files_skipped_vendored = check_links(registry)
    unlinked_info, resources_checked = check_readme_coverage()

    # Build human-readable findings (same as before)
    findings = []
    for info in links_info:
        findings.append(
            f"{info['file_rel']}:{info['line_no']}: broken-link -> {info['raw_target']}"
        )
    for info in unlinked_info:
        findings.append(
            f"README.md: undocumented -> {info['kind']}/{info['name']} "
            f"(add a row linking {info['path_rel'].as_posix()})"
        )

    if args.json:
        # Emit JSON report
        report = {
            "pass": len(findings) == 0,
            "markdown_files_scanned": files_scanned,
            "links_resolved": links_checked,
            "resources_checked": resources_checked,
            "files_skipped_as_vendored": files_skipped_vendored,
            "broken_links": [
                {
                    "file": str(info["file_rel"]),
                    "raw_link_target": info["raw_target"],
                    "resolved_path": str(info["resolved_path"]),
                }
                for info in links_info
            ],
            "unlinked_resources": [str(info["path_rel"]) for info in unlinked_info],
        }
        print(json.dumps(report))
        return 0 if report["pass"] else 1
    else:
        # Emit human-readable report (unchanged)
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
