#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

When invoked with --json, emits a machine-readable JSON object to stdout instead of
the human-readable report. The JSON shape is:

{
    "passed": bool,  # True if no broken links and no unlinked resources
    "counts": {
        "markdown_files_scanned": int,  # non-vendored markdown files that exist
        # on disk and were processed
        "links_resolved": int,  # links examined for existence (after skipping
        # HTTP/HTTPS/mailto/# anchors and pure anchors)
        "resources_checked": int,  # number of resources discovered by the checker
        "files_skipped_as_vendored": int,  # markdown files skipped due to vendored exemption
    },
    "broken_links": [  # each representing a broken relative link in a markdown file
        {
            "file": str,  # path of markdown file containing the link
            # relative to repo root
            "line": int,  # line number (1-indexed) of the link
            "raw_target": str,  # the link target as found in the markdown (before fragment)
            "resolved_path": str,  # the resolved absolute path that did not exist
            # relative to repo root
        }
    ],
    "unlinked_resources": [  # each representing a resource not linked from the README
        {
            "resource": str  # path of the resource, relative to repo root
        }
    ]
}

Without --json, the output is human-readable and unchanged from the original behavior.
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


def _check_links_structured(registry: list[dict]) -> tuple[list[dict], int, int, int]:
    """Check markdown links, returning structured data.

    Returns:
        tuple: (broken_links, markdown_files_scanned, links_resolved, files_skipped_as_vendored)
            broken_links: list of dicts, each with keys:
                file (str): markdown file containing the link
                # relative to repo root
                line (int): line number (1-indexed) of the link
                raw_target (str): the link target as found in the markdown (before fragment)
                resolved_path (str): the resolved absolute path that did not exist
                # relative to repo root
            markdown_files_scanned: count of non-vendored markdown files that exist
            # on disk and were processed
            links_resolved: count of links examined for existence (after skipping
            # HTTP/HTTPS/mailto/# anchors and pure anchors)
            files_skipped_as_vendored: count of markdown files skipped due to vendored exemption
    """
    broken_links = []
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
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    resolved_path = (md.parent / bare).resolve().relative_to(ROOT)
                    broken_links.append(
                        {
                            "file": str(rel),
                            "line": line_no,
                            "raw_target": target,
                            "resolved_path": str(resolved_path),
                        }
                    )
    return broken_links, markdown_files_scanned, links_resolved, files_skipped_as_vendored


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ROOT / p for p in out.split("\0") if p]


def _check_readme_coverage_structured() -> tuple[list[dict], int]:
    """Check README coverage, returning structured data.

    Returns:
        tuple: (unlinked_resources, resources_checked)
            unlinked_resources: list of dicts, each with keys:
                resource (str): path of the resource, relative to repo root
                kind (str): the kind of the resource (e.g., 'skill', 'agent')
                name (str): the name of the resource
            resources_checked: int, number of resources discovered by the checker
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    unlinked_resources = []
    resources = discover([])
    resources_checked = len(resources)
    for item in resources:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            unlinked_resources.append(
                {
                    "resource": str(item.src.relative_to(ROOT)),
                    "kind": item.kind,
                    "name": item.name,
                }
            )
    return unlinked_resources, resources_checked


def check_links(registry: list[dict]) -> list[str]:
    """Return human-readable findings for broken markdown links.

    This function exists to maintain compatibility with existing tests.
    New code should use _check_links_structured.
    """
    broken_links, _, _, _ = _check_links_structured(registry)
    findings = []
    for bl in broken_links:
        findings.append(f"{bl['file']}:{bl['line']}: broken-link -> {bl['raw_target']}")
    return findings


def check_readme_coverage() -> list[str]:
    """Return human-readable findings for README coverage.

    This function exists to maintain compatibility with existing tests.
    New code should use _check_readme_coverage_structured.
    """
    unlinked_resources, _ = _check_readme_coverage_structured()
    findings = []
    for ur in unlinked_resources:
        findings.append(
            f"README.md: undocumented -> {ur['kind']}/{ur['name']} "
            f"(add a row linking {ur['resource']})"
        )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args, unknown = parser.parse_known_args()
    if unknown:
        # If there are unknown arguments, we let argparse print an error and exit.
        # We'll re-parse with error handling to get the standard error message.
        parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    if args.json:
        broken_links, markdown_files_scanned, links_resolved, files_skipped_as_vendored = (
            _check_links_structured(registry)
        )
        unlinked_resources, resources_checked = _check_readme_coverage_structured()

        passed = not broken_links and not unlinked_resources

        result = {
            "passed": passed,
            "counts": {
                "markdown_files_scanned": markdown_files_scanned,
                "links_resolved": links_resolved,
                "resources_checked": resources_checked,
                "files_skipped_as_vendored": files_skipped_as_vendored,
            },
            "broken_links": [
                {
                    "file": bl["file"],
                    "line": bl["line"],
                    "raw_target": bl["raw_target"],
                    "resolved_path": bl["resolved_path"],
                }
                for bl in broken_links
            ],
            "unlinked_resources": [
                {
                    "resource": ur["resource"],
                }
                for ur in unlinked_resources
            ],
        }

        print(json.dumps(result))
        return 0 if passed else 1
    else:
        findings = check_links(registry) + check_readme_coverage()
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
