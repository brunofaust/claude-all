#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With the --json flag, emits a JSON object to stdout instead of the human-readable
report. The JSON object has the following shape:

{
    "pass": boolean,  # True if no findings, False otherwise
    "counts": {
        "markdown_files_scanned": int,  # non-vendored markdown files that exist
        "links_resolved": int,          # number of link targets examined (after filtering)
        "resources_checked": int,       # number of items returned by discover([])
        "files_skipped_as_vendored": int,  # vendored markdown files (regardless of existence)
    },
    "broken_links": [
        {
            "file": string,  # markdown file containing the link, relative to repo root
            "line": int,     # line number in that file (1-indexed)
            "target": string, # raw link target as found in the markdown
            "resolved_path": string  # absolute path that was checked and did not exist
        }
    ],
    "unlinked_resources": [
        string  # path of the resource's source file, relative to repo root
    ]
}

Without --json, the output is the same human-readable format as before.
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


def check_links(registry: list[dict]) -> tuple[list[str], int, list[dict]]:
    findings = []
    links_checked = 0
    broken_links = []
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
                links_checked += 1
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    findings.append(f"{rel}:{line_no}: broken-link -> {target}")
                    broken_links.append(
                        {
                            "file": str(rel),
                            "line": line_no,
                            "target": target,
                            "resolved_path": str((md.parent / bare).resolve()),
                        }
                    )
    return findings, links_checked, broken_links


def check_readme_coverage() -> tuple[list[str], int, list[str]]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    findings = []
    unlinked_resources = []
    for item in items:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            rel_path = item.src.relative_to(ROOT).as_posix()
            findings.append(
                f"README.md: undocumented -> {item.kind}/{item.name} (add a row linking {rel_path})"
            )
            unlinked_resources.append(rel_path)
    return findings, len(items), unlinked_resources


def main() -> int:
    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    json_mode = "--json" in sys.argv[1:]

    # Count markdown files
    markdown_files = tracked_markdown()
    vendored_skipped = sum(1 for md in markdown_files if is_vendored(md, registry))
    scanned_count = sum(1 for md in markdown_files if not is_vendored(md, registry) and md.exists())

    # Run checks
    link_findings, links_checked, broken_links = check_links(registry)
    readme_findings, resources_checked, unlinked_resources = check_readme_coverage()
    findings = link_findings + readme_findings
    pass_bool = len(findings) == 0

    if json_mode:
        # Emit JSON to stdout
        data = {
            "pass": pass_bool,
            "counts": {
                "markdown_files_scanned": scanned_count,
                "links_resolved": links_checked,
                "resources_checked": resources_checked,
                "files_skipped_as_vendored": vendored_skipped,
            },
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }
        print(json.dumps(data, separators=(",", ":")))
    else:
        # Human-readable output (unchanged)
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
