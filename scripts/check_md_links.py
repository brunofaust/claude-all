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

**JSON output mode**
When invoked with `--json`, the script outputs a single JSON object to stdout
containing the results in a machine-readable format. The JSON schema is:

{
  "passed": boolean,
  "counts": {
    "markdown_files_scanned": integer,
    "links_resolved": integer,
    "resources_checked": integer,
    "files_skipped_as_vendored": integer
  },
  "broken_links": [
    {
      "file": string,   // relative path from repository root
      "line": integer,  // 1-based line number in the markdown file
      "target": string, // the raw link target as found in the markdown
      "resolved_path": string   // absolute path that was checked and did not exist
    }
  ],
  "unlinked_resources": [
    {
      "kind": string,   // e.g., "skill", "agent"
      "name": string,   // the resource name
      "src": string     // relative path from repository root to the resource's source file
    }
  ]
}

The overall pass/fail is indicated by "passed": true when there are no broken links
and no unlinked resources.

Diagnostic messages (if any) are written to stderr; stdout contains only the JSON
object when `--json` is specified.

Without `--json`, the output and exit code are unchanged from the original behavior.
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


def compute_link_data(registry: list[dict]):
    """Compute link checking data for JSON output.

    Returns a tuple (files_scanned, files_skipped_as_vendored, links_resolved, broken_links)
    where:
        files_scanned: number of non-vendored markdown files that exist
        files_skipped_as_vendored: number of markdown files skipped due to vendored exemption
        links_resolved: number of link targets attempted to resolve (excluding skipped prefixes and pure anchors)
        broken_links: list of dicts, each with keys: file (str, relative to ROOT), line (int),
                      target (str), resolved_path (str, absolute)
    """
    files_scanned = 0
    files_skipped_as_vendored = 0
    links_resolved = 0
    broken_links = []

    for md in tracked_markdown():
        if is_vendored(md, registry):
            files_skipped_as_vendored += 1
            continue
        if not md.exists():
            continue
        files_scanned += 1
        text = md.read_text()
        for line_no, line in strip_code_blocks(text):
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
                            "file": rel.as_posix(),
                            "line": line_no,
                            "target": target,
                            "resolved_path": (md.parent / bare).resolve().as_posix(),
                        }
                    )
    return files_scanned, files_skipped_as_vendored, links_resolved, broken_links


def compute_readme_data():
    """Compute README coverage data for JSON output.

    Returns a tuple (resources_checked, unlinked_resources) where:
        resources_checked: number of resources discovered by `discover([])`
        unlinked_resources: list of dicts, each with keys: kind (str), name (str), src (str, relative to ROOT)
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    resources = discover([])
    resources_checked = len(resources)
    unlinked_resources = []
    for item in resources:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            unlinked_resources.append(
                {"kind": item.kind, "name": item.name, "src": item.src.relative_to(ROOT).as_posix()}
            )
    return resources_checked, unlinked_resources


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    if args.json:
        # JSON mode: compute structured data and output JSON to stdout
        files_scanned, files_skipped_as_vendored, links_resolved, broken_links = compute_link_data(
            registry
        )
        resources_checked, unlinked_resources = compute_readme_data()

        passed = len(broken_links) == 0 and len(unlinked_resources) == 0

        result = {
            "passed": passed,
            "counts": {
                "markdown_files_scanned": files_scanned,
                "links_resolved": links_resolved,
                "resources_checked": resources_checked,
                "files_skipped_as_vendored": files_skipped_as_vendored,
            },
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }
        print(json.dumps(result))
        return 0 if passed else 1
    else:
        # Default behavior: human-readable output
        findings = check_links(registry) + check_readme_coverage()
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
