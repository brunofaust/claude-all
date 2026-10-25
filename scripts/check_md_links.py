#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

--json flag: when supplied, emits a single machine-readable JSON object to stdout
instead of the human-formatted report. The JSON carries:

{
    "pass": bool,              # overall pass/fail
    "markdown_files_scanned": int,
    "links_resolved": int,
    "files_skipped_vendored": int,
    "broken_links": [          # list of broken link details
        {
            "containing_file": str,
            "raw_link_target": str,
            "resolved_path": str
        }
    ],
    "unlinked_resources": [   # list of unlinked resource paths
        str
    ]
}

Human output stays the default and stays byte-identical — this is additive.
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


def check_links(registry: list[dict]) -> dict:
    """Check markdown links and return structured results.

    Returns a dict with:
    - markdown_files_scanned: count of .md files tracked by git
    - links_resolved: count of link resolutions attempted
    - files_skipped_vendored: count of files skipped as vendored
    - broken_links: list of dicts with containing_file, raw_link_target, resolved_path
    """
    markdown_files_scanned = 0
    links_resolved = 0
    files_skipped_vendored = 0
    broken_links = []

    for md in tracked_markdown():
        markdown_files_scanned += 1
        if is_vendored(md, registry):
            files_skipped_vendored += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
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
                    broken_links.append(
                        {
                            "containing_file": str(rel),
                            "raw_link_target": target,
                            "resolved_path": str(resolved),
                        }
                    )

    return {
        "markdown_files_scanned": markdown_files_scanned,
        "links_resolved": links_resolved,
        "files_skipped_vendored": files_skipped_vendored,
        "broken_links": broken_links,
    }


def check_readme_coverage() -> dict:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    unlinked_resources = [
        f"README.md: undocumented -> {item.kind}/{item.name} "
        f"(add a row linking {item.src.relative_to(ROOT).as_posix()})"
        for item in discover([])
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme
    ]
    # Count how many resources were checked by discovering total
    # discover([]) returns all discovered resources; we track how many were found
    all_resources = list(discover([]))
    resources_checked = len(all_resources)

    return {
        "resources_checked": resources_checked,
        "unlinked_resources": unlinked_resources,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Markdown link and README coverage gate")
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit machine-readable JSON to stdout instead of human-formatted report",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    links_result = check_links(registry)
    readme_result = check_readme_coverage()

    if args.json:
        output = {
            "pass": not (links_result["broken_links"] or readme_result["unlinked_resources"]),
            "markdown_files_scanned": links_result["markdown_files_scanned"],
            "links_resolved": links_result["links_resolved"],
            "files_skipped_vendored": links_result["files_skipped_vendored"],
            "broken_links": links_result["broken_links"],
            "unlinked_resources": readme_result["unlinked_resources"],
        }
        print(json.dumps(output, indent=2))
        # Exit code: 0 if pass, 1 if findings (same as human mode)
        if links_result["broken_links"] or readme_result["unlinked_resources"]:
            return 1
        return 0
    else:
        # Human-readable output (unchanged behavior)
        for finding in links_result["broken_links"]:
            rel = Path(finding["containing_file"]).relative_to(ROOT)
            print(f"{rel}:{finding['raw_link_target']} -> broken")
        for finding in readme_result["unlinked_resources"]:
            print(finding)
        total_findings = len(links_result["broken_links"]) + len(
            readme_result["unlinked_resources"]
        )
        if total_findings:
            print(f"\n{total_findings} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
