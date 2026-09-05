#!/usr/bin/env python3
"""check_md_links.py

Prek gate enforcing two rules:
* Relative markdown links resolve — four cross-skill links once shipped one {{../}} short, one of them in an already-merged PR.
* Every resource is linked from the README — the README tables link each resource's source file, so "is it linked?" is a machine-answerable proxy for "is it documented?".

Vendored files are exempt from rule 1 (kept byte-identical to upstream, so their upstream-relative links legitimately do not resolve here). Files under a vendored entry's {{local_only}} are ours and stay checked.

JSON output mode (--json):
When the --json flag is provided, the script emits a single machine-readable JSON object to stdout instead of the human-formatted report. The JSON contains:
* pass (boolean): overall pass/fail status
* counts (object): inspection statistics
  * markdown_files_scanned (int): total markdown files found via git ls-files
  * links_resolved (int): total link targets examined (after filtering)
  * resources_checked (int): number of resources checked for README coverage
  * files_skipped_as_vendored (int): number of files skipped due to vendored exemption
* broken_links (array): details of each broken link
  * file (str): containing file path relative to repository root
  * target (str): raw link target as written in markdown
  * resolved_path (str): absolute path that was checked and did not exist
* unlinked_resources (array): paths of resources not linked from README (relative to repository root)

Diagnostics, if any, go to stderr. Without --json, output and exit codes are unchanged from today. Exit codes are identical in both modes for the same input.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"^```.*")
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
CODE_SPAN = re.compile(r"`[^`]*`")
SKIP_PREFIX = ("http://", "https://", "mailto:", "#", "tel:", "/")


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


def _collect_json_data(registry: list[dict]) -> dict:
    """Collect all data needed for JSON output.

    Returns a dictionary with the structure expected for JSON output.
    """
    # Get all markdown files
    all_markdown_files = list(tracked_markdown())
    markdown_files_scanned = len(all_markdown_files)

    # Initialize counters and collections
    links_resolved = 0
    broken_links = []
    files_skipped_as_vendored = 0

    # Process each markdown file for link checking
    for md in all_markdown_files:
        if is_vendored(md, registry):
            files_skipped_as_vendored += 1
            continue
        if not md.exists():
            continue
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                links_resolved += 1  # Count this link target as examined
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                resolved = (md.parent / bare).resolve()
                if not resolved.exists():
                    rel = md.relative_to(ROOT)
                    broken_links.append(
                        {"file": str(rel), "target": target, "resolved_path": str(resolved)}
                    )

    # Get README coverage data
    coverage_results = check_readme_coverage()
    resources_checked = len(coverage_results)
    unlinked_resources = [
        item.src.relative_to(ROOT).as_posix()
        for item in discover([])
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in (ROOT / "README.md").read_text()
    ]

    # Determine overall pass/fail
    pass_status = len(broken_links) == 0 and len(unlinked_resources) == 0

    return {
        "pass": pass_status,
        "counts": {
            "markdown_files_scanned": markdown_files_scanned,
            "links_resolved": links_resolved,
            "resources_checked": resources_checked,
            "files_skipped_as_vendored": files_skipped_as_vendored,
        },
        "broken_links": broken_links,
        "unlinked_resources": unlinked_resources,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check markdown links and README coverage")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable report",
    )
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    if args.json:
        # JSON output mode
        data = _collect_json_data(registry)
        print(json.dumps(data, indent=None))  # Compact JSON
        return 0 if data["pass"] else 1
    else:
        # Original human-readable behavior
        findings = check_links(registry) + check_readme_coverage()
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
