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

JSON output (--json):
  Emits a single JSON object to stdout with the following stable schema:

  {
    "passed": true | false,
    "counts": {
      "markdown_files_scanned": int,
      "links_checked": int,
      "resources_checked": int,
      "vendored_files_skipped": int
    },
    "broken_links": [
      {
        "file": "relative/path/to/file.md",
        "line": 42,
        "raw_target": "../missing.md",
        "resolved_path": "absolute/or/relative/path/that/does/not/exist"
      },
      ...
    ],
    "unlinked_resources": [
      "relative/path/to/resource.md",
      ...
    ]
  }

  Diagnostics (if any) go to stderr. Exit code is identical to non-JSON mode:
  0 on pass, 1 on any finding.
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


def check_links(registry: list[dict]) -> tuple[list[dict], int, int, int]:
    """Check markdown links in tracked files.

    Returns:
        Tuple of (broken_links, markdown_files_scanned, links_checked, vendored_files_skipped)
        where broken_links is a list of dicts with keys: file, line, raw_target, resolved_path
    """
    broken_links = []
    markdown_files_scanned = 0
    links_checked = 0
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
                links_checked += 1
                resolved_path = (md.parent / bare).resolve()
                if not resolved_path.exists():
                    rel = md.relative_to(ROOT)
                    broken_links.append(
                        {
                            "file": str(rel),
                            "line": line_no,
                            "raw_target": target,
                            "resolved_path": str(resolved_path),
                        }
                    )
    return broken_links, markdown_files_scanned, links_checked, vendored_files_skipped


def check_readme_coverage() -> tuple[list[str], int]:
    """Check that every resource is linked from README.

    Returns:
        Tuple of (unlinked_resources, resources_checked)
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    resources = list(discover([]))
    unlinked = []
    for item in resources:
        rel_path = item.src.relative_to(ROOT).as_posix()
        if f"]({rel_path})" not in readme:
            unlinked.append(rel_path)
    return unlinked, len(resources)


def format_human_output(broken_links: list[dict], unlinked_resources: list[str]) -> list[str]:
    """Format findings for human-readable output (the original format)."""
    findings = []
    for bl in broken_links:
        findings.append(f"{bl['file']}:{bl['line']}: broken-link -> {bl['raw_target']}")
    for ur in unlinked_resources:
        findings.append(f"README.md: undocumented -> {ur} (add a row linking {ur})")
    return findings


def format_json_output(
    broken_links: list[dict],
    unlinked_resources: list[str],
    markdown_files_scanned: int,
    links_checked: int,
    resources_checked: int,
    vendored_files_skipped: int,
) -> dict:
    """Format findings as a JSON-serializable dict."""
    passed = len(broken_links) == 0 and len(unlinked_resources) == 0
    return {
        "passed": passed,
        "counts": {
            "markdown_files_scanned": markdown_files_scanned,
            "links_checked": links_checked,
            "resources_checked": resources_checked,
            "vendored_files_skipped": vendored_files_skipped,
        },
        "broken_links": broken_links,
        "unlinked_resources": unlinked_resources,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check markdown links and README coverage",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable output",
    )
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    (
        broken_links,
        markdown_files_scanned,
        links_checked,
        vendored_files_skipped,
    ) = check_links(registry)
    unlinked_resources, resources_checked = check_readme_coverage()

    has_findings = len(broken_links) > 0 or len(unlinked_resources) > 0

    if args.json:
        output = format_json_output(
            broken_links,
            unlinked_resources,
            markdown_files_scanned,
            links_checked,
            resources_checked,
            vendored_files_skipped,
        )
        json.dump(output, sys.stdout)
        sys.stdout.write("\n")
    else:
        findings = format_human_output(broken_links, unlinked_resources)
        for finding in findings:
            print(finding)
        if has_findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)

    return 1 if has_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
