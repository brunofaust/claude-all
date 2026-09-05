#!/usr/bin/env python3
"""check_md_links.py

*Relative markdown links resolve* — four cross-skill links once shipped one {{../}}
short, one of them in an already-merged PR.
*Every resource is linked from the README* — the README tables link each resource's
source file, so "is it linked?" is a machine-answerable proxy for "is it
documented?".

Vendored files are exempt from rule 1 (kept byte-identical to upstream, so their
upstream-relative links legitimately do not resolve here). Files under a vendored
entry's {{local_only}} are ours and stay checked.

The script emits a human-readable report by default. Use the {{--json}} flag
to emit a machine-readable JSON object with:
- Overall pass/fail status
- Counts: markdown files scanned, links resolved, resources checked, files
  skipped as vendored
- Details for each broken link: containing file, raw link target, resolved
  path that did not exist
- Paths of unlinked resources
"""

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from subprocess import run

# Constants
ROOT = Path(__file__).resolve().parent.parent
SKIP_PREFIX = (
    "http://",
    "https://",
    "mailto:",
    "#",
    "tel:",
    "/",
)
LINK = re.compile(r"\[[^\]]*\]\([^)]*\)")
CODE_SPAN = re.compile(r"`[^`]*`")


def tracked_markdown() -> list[Path]:
    """Return all markdown files tracked by git."""
    out = run(
        ["git", "ls-files", "-z", "*.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ROOT / p for p in out.split("\0") if p]


def is_vendored(path: Path, registry: list[dict]) -> bool:
    """Check if a path is vendored (exempt from link validation)."""
    for entry in registry:
        vendor_path = ROOT / entry["path"]
        if entry.get("vendor_mode") == "dir" and path.is_relative_to(vendor_path):
            if "local_only" in entry:
                # Check if path is in the local_only allowlist
                rel_path = path.relative_to(vendor_path)
                if str(rel_path) not in entry["local_only"]:
                    return True
            else:
                return True
        elif "files" in entry and path == vendor_path / entry["files"]:
            return True
    return False


def strip_code_blocks(text: str) -> Iterable[tuple[int, str]]:
    """Yield (line_number, line) pairs, excluding fenced code blocks."""
    lines = text.splitlines()
    in_code_block = False
    for i, line in enumerate(lines, start=1):
        if line.startswith("```") or line.startswith("~~~"):
            in_code_block = not in_code_block
            continue
        if not in_code_block:
            yield i, line


def check_links(registry: list[dict]) -> list[str]:
    """Return list of broken-link findings as strings."""
    findings = []
    for md in tracked_markdown():
        if is_vendored(md, registry):
            continue
        if not md.exists():
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
    """Return list of undocumented resource findings as strings."""
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
    """Collect structured data for JSON output."""
    markdown_files = list(tracked_markdown())
    markdown_files_scanned = len([f for f in markdown_files if not is_vendored(f, registry)])
    files_skipped_as_vendored = len([f for f in markdown_files if is_vendored(f, registry)])

    links_resolved = 0
    broken_links = []

    for md in markdown_files:
        if is_vendored(md, registry):
            continue
        if not md.exists():
            continue
        for _line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                links_resolved += 1
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                resolved = (md.parent / bare).resolve()
                if not resolved.exists():
                    rel = md.relative_to(ROOT)
                    # Try to make resolved path relative to ROOT, fall back to absolute
                    try:
                        resolved_path = str(resolved.relative_to(ROOT))
                    except ValueError:
                        resolved_path = str(resolved)
                    broken_links.append(
                        {
                            "file": str(rel),
                            "target": target,
                            "resolved_path": resolved_path,
                        }
                    )

    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    resources_data = check_readme_coverage()
    resources_checked = len(resources_data)
    unlinked_resources = [
        item.src.relative_to(ROOT).as_posix()
        for item in discover([])
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in (ROOT / "README.md").read_text()
    ]

    has_findings = bool(broken_links) or bool(unlinked_resources)

    return {
        "pass": not has_findings,
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args, unknown = parser.parse_known_args()

    # Handle unknown args by passing them through (for help, etc.)
    if unknown:
        sys.argv = [sys.argv[0], *unknown]
        parser = argparse.ArgumentParser()
        parser.add_argument("--json", action="store_true", help="Emit JSON output")
        args, _ = parser.parse_known_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    if args.json:
        data = _collect_json_data(registry)
        print(json.dumps(data, indent=None, separators=(",", ":")))
        return 0 if data["pass"] else 1
    else:
        findings = check_links(registry) + check_readme_coverage()
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
