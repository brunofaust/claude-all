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

JSON output (--json flag)
-------------------------
When the `--json` flag is provided, a single compact JSON object is emitted to
stdout instead of the human-readable report. The object shape:

{
  "pass": true | false,
  "counts": {
    "markdown_files_scanned": int,
    "links_resolved": int,
    "resources_checked": int,
    "files_skipped_as_vendored": int
  },
  "broken_links": [
    {
      "file": "relative/path/to/file.md",
      "line": int,
      "target": "raw link target",
      "resolved_path": "relative/path/that/does/not/exist"
    },
    ...
  ],
  "unlinked_resources": [
    "relative/path/to/resource.md",
    ...
  ]
}

- `pass`: Overall gate result (true = no findings, false = any findings).
- `counts.markdown_files_scanned`: Non-vendored markdown files actually read
  and checked.
- `counts.links_resolved`: Link targets examined (after filtering SKIP_PREFIX,
  anchors, code spans).
- `counts.resources_checked`: Total resources discovered by `discover([])`
  (the pool inspected for README coverage).
- `counts.files_skipped_as_vendored`: Markdown files skipped because they are
  vendored upstream copies.
- `broken_links`: One entry per broken relative link. `file` and
  `resolved_path` are relative to the repo root.
- `unlinked_resources`: One entry per resource not linked from README.md.
  Paths are relative to the repo root.
- Diagnostics (if any) go to stderr; stdout contains only the JSON object.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parent.parent

# [label](target) — skip images, absolute URLs, anchors and mailto. A leading `/` is
# a site-absolute URL (the SEO skill's llms.txt examples), never a repo path.
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "#", "tel:", "/")
FENCE = re.compile(r"^\s*(```|~~~)")
# Inline code spans are not links: `def first[T](...)` reads as [T](...).
CODE_SPAN = re.compile(r"`[^`]*`")


class BrokenLink(TypedDict):
    file: str
    line: int
    target: str
    resolved_path: str


class CheckResult(TypedDict):
    pass_: bool
    counts: dict[str, int]
    broken_links: list[BrokenLink]
    unlinked_resources: list[str]


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


def check_links(registry: list[dict]) -> tuple[list[BrokenLink], dict[str, int]]:
    """Check all non-vendored markdown files for broken relative links.

    Returns:
        Tuple of (broken_links, counts) where counts contains:
        - markdown_files_scanned: non-vendored files actually read
        - links_resolved: link targets examined (after filtering)
        - files_skipped_as_vendored: vendored files skipped
    """
    broken_links: list[BrokenLink] = []
    markdown_files_scanned = 0
    links_resolved = 0
    files_skipped_as_vendored = 0

    for md in tracked_markdown():
        if is_vendored(md, registry):
            files_skipped_as_vendored += 1
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
                resolved_abs = (md.parent / bare).resolve()
                if not resolved_abs.exists():
                    rel_file = md.relative_to(ROOT)
                    # resolved_path relative to ROOT for consistency
                    try:
                        resolved_rel = resolved_abs.relative_to(ROOT)
                    except ValueError:
                        # Outside repo (shouldn't happen for relative links, but be safe)
                        resolved_rel = resolved_abs
                    broken_links.append(
                        {
                            "file": rel_file.as_posix(),
                            "line": line_no,
                            "target": target,
                            "resolved_path": resolved_rel.as_posix(),
                        }
                    )

    counts = {
        "markdown_files_scanned": markdown_files_scanned,
        "links_resolved": links_resolved,
        "files_skipped_as_vendored": files_skipped_as_vendored,
    }
    return broken_links, counts


def check_readme_coverage() -> tuple[list[str], int]:
    """Check README coverage for all discovered resources.

    Returns:
        Tuple of (unlinked_resources, resources_checked) where
        resources_checked is the total number of resources discovered.
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    all_resources = list(discover([]))
    unlinked = [
        item.src.relative_to(ROOT).as_posix()
        for item in all_resources
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme
    ]
    return unlinked, len(all_resources)


def build_json_result(
    broken_links: list[BrokenLink],
    unlinked_resources: list[str],
    counts: dict[str, int],
    resources_checked: int,
) -> CheckResult:
    """Build the JSON result object."""
    return {
        "pass_": len(broken_links) == 0 and len(unlinked_resources) == 0,
        "counts": {
            "markdown_files_scanned": counts["markdown_files_scanned"],
            "links_resolved": counts["links_resolved"],
            "resources_checked": resources_checked,
            "files_skipped_as_vendored": counts["files_skipped_as_vendored"],
        },
        "broken_links": broken_links,
        "unlinked_resources": unlinked_resources,
    }


def emit_json(result: CheckResult) -> None:
    """Emit a single compact JSON object to stdout."""
    json.dump(result, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")


def emit_human(broken_links: list[BrokenLink], unlinked_resources: list[str]) -> list[str]:
    """Convert findings to human-readable format."""
    findings = []
    for bl in broken_links:
        findings.append(f"{bl['file']}:{bl['line']}: broken-link -> {bl['target']}")
    for ur in unlinked_resources:
        findings.append(f"README.md: undocumented -> {ur} (add a row linking {ur})")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check markdown links and README coverage",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single machine-readable JSON object to stdout",
    )
    args = parser.parse_args(argv)

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    broken_links, link_counts = check_links(registry)
    unlinked_resources, resources_checked = check_readme_coverage()

    all_counts = {**link_counts, "resources_checked": resources_checked}
    result = build_json_result(broken_links, unlinked_resources, all_counts, resources_checked)

    if args.json:
        emit_json(result)
        # No diagnostic count line to stderr in JSON mode — the JSON has it all.
        return 0 if result["pass_"] else 1

    # Human mode (default) — unchanged behavior
    findings = emit_human(broken_links, unlinked_resources)
    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
