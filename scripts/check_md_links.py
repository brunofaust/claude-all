#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

The script supports a `--json` flag that outputs a machine-readable JSON object
instead of human-readable report; JSON shape below:

{
    "passed": bool,  # True if no findings, False otherwise
    "markdown_files_scanned": int,   # Number of Markdown files scanned (excluding vendored)
    "links_resolved": int,  # Total Markdown links resolved (non-vendored)
    "resources_checked": int,  # Resources checked for README linkage
    "files_skipped_as_vendored": int,  # Markdown files skipped as vendored
    "broken_links": [                # List of broken links found
        {
            "file": str,  # Markdown file with broken link (repo-relative)
            "line": int,             # Line number in the file (1-indexed)
            "target": str,  # Raw link target from Markdown
            "resolved_path": str  # Resolved path that was checked
        }
    ],
    "unlinked_resources": [          # List of resources not linked from the README
        {
            "kind": str,  # Resource kind (e.g., skill, agent)
            "name": str,  # Resource name
            "path": str  # Resource path (repo-relative)
        }
    ]
}

Without `--json`, the script outputs a human-readable list of findings to stdout
and a count of findings to stderr, and exits with 0 if no findings, 1 otherwise.
With `--json`, the script outputs only the JSON object to stdout, and diagnostics
(if any) go to stderr. The exit code is the same as in non-JSON mode for the same input.
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


def _check_links_data(registry: list[dict]) -> tuple[list[str], dict]:
    findings = []
    markdown_files_scanned = 0
    links_resolved = 0
    broken_links = []
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
                    findings.append(f"{rel}:{line_no}: broken-link -> {target}")
                    broken_links.append(
                        {
                            "file": str(rel),
                            "line": line_no,
                            "target": target,
                            "resolved_path": str((md.parent / bare).resolve()),
                        }
                    )
    return findings, {
        "markdown_files_scanned": markdown_files_scanned,
        "links_resolved": links_resolved,
        "broken_links": broken_links,
        "files_skipped_as_vendored": files_skipped_as_vendored,
    }


def check_links(registry: list[dict]) -> list[str]:
    findings, _ = _check_links_data(registry)
    return findings


def _check_readme_coverage_data() -> tuple[list[str], dict]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = list(discover([]))
    findings = []
    unlinked_resources = []
    for item in items:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            findings.append(
                f"README.md: undocumented -> {item.kind}/{item.name} "
                f"(add a row linking {item.src.relative_to(ROOT).as_posix()})"
            )
            unlinked_resources.append(
                {"kind": item.kind, "name": item.name, "path": str(item.src.relative_to(ROOT))}
            )
    return findings, {"resources_checked": len(items), "unlinked_resources": unlinked_resources}


def check_readme_coverage() -> list[str]:
    findings, _ = _check_readme_coverage_data()
    return findings


def main() -> int:
    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    json_mode = "--json" in sys.argv
    if json_mode:
        link_findings, link_data = _check_links_data(registry)
        coverage_findings, coverage_data = _check_readme_coverage_data()
        findings = link_findings + coverage_findings
        data = {
            "passed": len(findings) == 0,
            "markdown_files_scanned": link_data["markdown_files_scanned"],
            "links_resolved": link_data["links_resolved"],
            "resources_checked": coverage_data["resources_checked"],
            "files_skipped_as_vendored": link_data["files_skipped_as_vendored"],
            "broken_links": link_data["broken_links"],
            "unlinked_resources": coverage_data["unlinked_resources"],
        }
        print(json.dumps(data))
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
        return 0 if len(findings) == 0 else 1
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
