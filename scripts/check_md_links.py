#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With --json, output a machine-readable JSON object to stdout instead of the
human-readable report. The JSON has the following shape:

{
    "pass": bool,                    # True if no findings, False otherwise
    "counts": {
        "markdown_files_scanned": int,   # Non-vendored Markdown files that exist on disk
        "links_resolved": int,           # Link targets examined (after filtering)
        "resources_checked": int,        # Resources discovered via claude_all.cli.discover
        "files_skipped_as_vendored": int # Markdown files skipped due to vendoring
    },
    "broken_links": [                 # Each broken relative link
        {
            "containing_file": str,   # Markdown file relative to repo root
            "raw_link_target": str,   # Link target as found in Markdown
            "resolved_path": str      # Absolute path checked that did not exist
        }
    ],
    "unlinked_resources": [           # Each resource not linked from README
        str                           # Resource path relative to repo root
    ]
}
Without --json, output and exit codes are unchanged from today.
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
LINK = re.compile(r"(?<!!)\[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
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


def check_links(registry: list[dict]):
    """Check Markdown links.

    Returns a tuple:
        (broken_links_records, mds_scanned, links_resolved, files_skipped_vendored)
    where:
        broken_links_records: list of dicts with keys:
            markdown_file: Path (the Markdown file)
            line_no: int (line number in the file)
            target: str (raw link target)
            bare: str (target without anchor)
        mds_scanned: int (non-vendored Markdown files that exist on disk)
        links_resolved: int (link targets examined after filtering)
        files_skipped_vendored: int (Markdown files skipped due to vendoring)
    """
    broken_links = []
    mds_scanned = 0
    links_resolved = 0
    files_skipped_vendored = 0
    for md in tracked_markdown():
        if is_vendored(md, registry):
            files_skipped_vendored += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        mds_scanned += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                links_resolved += 1
                if not (md.parent / bare).resolve().exists():
                    broken_links.append(
                        {
                            "markdown_file": md,
                            "line_no": line_no,
                            "target": target,
                            "bare": bare,
                        }
                    )
    return broken_links, mds_scanned, links_resolved, files_skipped_vendored


def check_readme_coverage():
    """Check README coverage of resources.

    Returns a tuple:
        (unlinked_items, resources_checked)
    where:
        unlinked_items: list of resource items (from discover) not linked from README
        resources_checked: int (number of resources discovered)
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    resources_checked = len(items)
    unlinked_items = [
        item for item in items if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme
    ]
    return unlinked_items, resources_checked


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON instead of human-readable report",
    )
    args, _ = parser.parse_known_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    link_results = check_links(registry)
    readme_results = check_readme_coverage()

    broken_links_records, mds_scanned, links_resolved, files_skipped_vendored = link_results
    unlinked_records, resources_checked = readme_results

    if args.json:
        # Build JSON output
        result = {
            "pass": len(broken_links_records) == 0 and len(unlinked_records) == 0,
            "counts": {
                "markdown_files_scanned": mds_scanned,
                "links_resolved": links_resolved,
                "resources_checked": resources_checked,
                "files_skipped_as_vendored": files_skipped_vendored,
            },
            "broken_links": [
                {
                    "containing_file": str(record["markdown_file"].relative_to(ROOT)),
                    "raw_link_target": record["target"],
                    "resolved_path": str(
                        (record["markdown_file"].parent / record["bare"]).resolve()
                    ),
                }
                for record in broken_links_records
            ],
            "unlinked_resources": [str(item.src.relative_to(ROOT)) for item in unlinked_records],
        }
        print(json.dumps(result))
        # In JSON mode, we do not output anything else to stdout.
        # We also do not output the finding count line to stderr.
        # Exit code is based on pass/fail.
        return 0 if result["pass"] else 1
    else:
        # Human-readable output (existing behavior)
        findings = []
        for record in broken_links_records:
            rel = record["markdown_file"].relative_to(ROOT)
            findings.append(f"{rel}:{record['line_no']}: broken-link -> {record['target']}")
        for item in unlinked_records:
            findings.append(
                f"README.md: undocumented -> {item.kind}/{item.name} "
                f"(add a row linking {item.src.relative_to(ROOT).as_posix()})"
            )
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
