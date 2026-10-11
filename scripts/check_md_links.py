#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

The script can output a machine-readable JSON report when invoked with `--json`.
The JSON object contains:
{
    "passed": bool,  # True if no broken links and all resources are linked
    "markdown_files_scanned": int,  # number of Markdown files inspected (non-vendored and existing)
    "links_resolved": int,  # number of relative links checked in those files
    "resources_checked": int,  # number of resources discovered by `claude_all.cli.discover`
    "files_skipped_as_vendored": int,  # number of Markdown files skipped due to vendored exemption
    "broken_links": [  # each object represents a broken relative link
        {
            "file": str,  # path of the Markdown file containing the link, relative to repo root
            "line": int,  # line number (1-indexed) of the link
            "target": str,  # the raw link target (without fragment or query)
            "resolved_path": str  # the absolute path that was checked and did not exist
        }
    ],
    "unlinked_resources": [  # each object represents a resource not linked from the README
        {
            "kind": str,  # e.g., "skill", "agent"
            "name": str,  # resource name as declared in its SKILL.md/agent.md frontmatter
            "src": str  # path to the resource's source file, relative to repo root
        }
    ]
}
Without `--json`, the script outputs a human-readable list of findings (one per line)
and exits with a non-zero status if any findings are found.
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
    broken_links = []
    scanned_markdown = 0
    links_resolved = 0
    vendored_skipped = 0
    for md in tracked_markdown():
        if is_vendored(md, registry):
            vendored_skipped += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        scanned_markdown += 1
        for line_no, line in strip_code_blocks(md.read_text()):
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
    return {
        "broken_links": broken_links,
        "scanned_markdown": scanned_markdown,
        "links_resolved": links_resolved,
        "vendored_skipped": vendored_skipped,
    }


def check_readme_coverage() -> dict:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    resources_checked = len(items)
    unlinked_resources = []
    for item in items:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            unlinked_resources.append(
                {"kind": item.kind, "name": item.name, "src": item.src.relative_to(ROOT).as_posix()}
            )
    return {"unlinked_resources": unlinked_resources, "resources_checked": resources_checked}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check markdown links and README coverage.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON instead of human-readable text.",
    )
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    links_data = check_links(registry)
    coverage_data = check_readme_coverage()

    passed = len(links_data["broken_links"]) == 0 and len(coverage_data["unlinked_resources"]) == 0

    if args.json:
        output = {
            "passed": passed,
            "markdown_files_scanned": links_data["scanned_markdown"],
            "links_resolved": links_data["links_resolved"],
            "resources_checked": coverage_data["resources_checked"],
            "files_skipped_as_vendored": links_data["vendored_skipped"],
            "broken_links": links_data["broken_links"],
            "unlinked_resources": coverage_data["unlinked_resources"],
        }
        print(json.dumps(output))
    else:
        # Human-readable output: same as before
        for bl in links_data["broken_links"]:
            print(f"{bl['file']}:{bl['line']}: broken-link -> {bl['target']}")
        for ul in coverage_data["unlinked_resources"]:
            print(
                f"README.md: undocumented -> {ul['kind']}/{ul['name']} (add a row linking {ul['src']})"
            )
        if not passed:
            total_findings = len(links_data["broken_links"]) + len(
                coverage_data["unlinked_resources"]
            )
            print(f"\n{total_findings} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
