#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With `--json`, output a machine-readable JSON object instead of the human-readable report.

JSON output format:
{
    "pass": boolean,  # True if no findings, False otherwise
    "counts": {
        "markdown_files_scanned": int,  # MD files scanned
        "links_resolved": int,          # Link targets checked
        "resources_checked": int,       # Resources discovered
        "files_skipped_as_vendored": int,  # Vendored files skipped
    },
    "broken_links": [  # list of objects, each representing a broken relative markdown link
        {
            "file": string,  # MD file with broken link
            "line": integer, # line number (1-indexed) of the broken link
            "target": string, # the raw link target as found in the markdown
            "resolved_path": string, # Checked path (absolute)
        }
    ],
    "unlinked_resources": [string],  # Unlinked resource paths
}
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


def _check_links_internal(registry: list[dict]) -> tuple[list[dict], dict]:
    broken_links = []
    counts = {
        "markdown_files_scanned": 0,
        "links_resolved": 0,
        "files_skipped_as_vendored": 0,
    }
    for md in tracked_markdown():
        if is_vendored(md, registry):
            counts["files_skipped_as_vendored"] += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        counts["markdown_files_scanned"] += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                counts["links_resolved"] += 1
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
    return broken_links, counts


def format_broken_link(broken_link: dict) -> str:
    return f"{broken_link['file']}:{broken_link['line']}: broken-link -> {broken_link['target']}"


def check_links(registry: list[dict]) -> list[str]:
    broken_links, _ = _check_links_internal(registry)
    return [format_broken_link(b) for b in broken_links]


def _check_readme_coverage_internal() -> tuple[list[dict], dict]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    unlinked_resources = []
    for item in items:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            unlinked_resources.append(
                {
                    "kind": item.kind,
                    "name": item.name,
                    "src": item.src.relative_to(ROOT).as_posix(),
                }
            )
    counts = {
        "resources_checked": len(items),
    }
    return unlinked_resources, counts


def format_unlinked_resource(unlinked_resource: dict) -> str:
    return f"README.md: undocumented -> {unlinked_resource['kind']}/{unlinked_resource['name']} (add a row linking {unlinked_resource['src']})"


def check_readme_coverage() -> list[str]:
    unlinked_resources, _ = _check_readme_coverage_internal()
    return [format_unlinked_resource(u) for u in unlinked_resources]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    broken_links, link_counts = _check_links_internal(registry)
    unlinked_resources, readme_counts = _check_readme_coverage_internal()

    findings: list[str] = []
    findings.extend(format_broken_link(b) for b in broken_links)
    findings.extend(format_unlinked_resource(u) for u in unlinked_resources)

    if args.json:
        # Build JSON output
        result = {
            "pass": len(findings) == 0,
            "counts": {
                "markdown_files_scanned": link_counts["markdown_files_scanned"],
                "links_resolved": link_counts["links_resolved"],
                "resources_checked": readme_counts["resources_checked"],
                "files_skipped_as_vendored": link_counts["files_skipped_as_vendored"],
            },
            "broken_links": broken_links,
            "unlinked_resources": [
                r["src"] for r in unlinked_resources
            ],  # as per ticket: string representing the resource path
        }
        print(json.dumps(result))
        return 0 if result["pass"] else 1
    else:
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
