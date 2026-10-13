#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

The script defaults to a human-readable report. With `--json`, it emits a machine-readable
JSON object to stdout instead, containing:

- passed: boolean, true if no broken links and all resources are linked from the README
- markdown_files_scanned: number of Markdown files examined for link checks
  (excluding vendored, missing, and the README.md file)
- links_resolved: number of non-skipped Markdown links checked
- resources_checked: number of resources discovered by `claude-all discover`
- files_skipped_as_vendored: number of Markdown files skipped due to vendored exemption
- broken_links: list of objects, each with:
    - file: string, path of the Markdown file containing the broken link
      (relative to repository root)
    - line: integer, line number (1-based) of the broken link
    - target: string, the raw link target as found in the Markdown
    - resolved: string, the absolute path that was checked and found missing
- unlinked_resources: list of strings, each being the path (relative to repository root) of a
    resource that is not linked from the README

Diagnostics (e.g., finding counts) are printed to stderr in both modes.
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


def collect_data(
    registry: list[dict],
) -> tuple[
    int,  # markdown_files_scanned
    int,  # links_resolved
    int,  # files_skipped_as_vendored
    int,  # resources_checked
    list[
        tuple[Path, int, str, Path]
    ],  # broken_links_raw: (file_relative_to_root, line_no, target, resolved_absolute)
    list[Path],  # unlinked_resources_raw: paths relative to root
]:
    markdown_files_scanned = 0
    links_resolved = 0
    files_skipped_as_vendored = 0
    broken_links_raw = []
    unlinked_resources_raw = []

    # Read README once for coverage check
    readme_text = (ROOT / "README.md").read_text()

    # Process markdown files for links
    for md in tracked_markdown():
        if is_vendored(md, registry):
            files_skipped_as_vendored += 1
            continue
        if not md.exists():
            # tracked-but-deleted file: skip entirely
            continue
        # Skip the README.md file in the root for the link scan
        if md == ROOT / "README.md":
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
                    rel_md = md.relative_to(ROOT)
                    resolved_path = (md.parent / bare).resolve()
                    broken_links_raw.append((rel_md, line_no, target, resolved_path))

    # Process resources for README coverage
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    resources_checked = 0
    for item in discover([]):
        resources_checked += 1
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme_text:
            unlinked_resources_raw.append(item.src.relative_to(ROOT))

    return (
        markdown_files_scanned,
        links_resolved,
        files_skipped_as_vendored,
        resources_checked,
        broken_links_raw,
        unlinked_resources_raw,
    )


def main() -> int:
    json_mode = "--json" in sys.argv
    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    if json_mode:
        (
            markdown_files_scanned,
            links_resolved,
            files_skipped_as_vendored,
            resources_checked,
            broken_links_raw,
            unlinked_resources_raw,
        ) = collect_data(registry)
        result = {
            "passed": len(broken_links_raw) == 0 and len(unlinked_resources_raw) == 0,
            "markdown_files_scanned": markdown_files_scanned,
            "links_resolved": links_resolved,
            "resources_checked": resources_checked,
            "files_skipped_as_vendored": files_skipped_as_vendored,
            "broken_links": [
                {
                    "file": str(file_rel),
                    "line": line_no,
                    "target": target,
                    "resolved": str(resolved_abs),
                }
                for file_rel, line_no, target, resolved_abs in broken_links_raw
            ],
            "unlinked_resources": [str(path) for path in unlinked_resources_raw],
        }
        print(json.dumps(result, indent=None))
        findings_count = len(broken_links_raw) + len(unlinked_resources_raw)
        if findings_count:
            print(f"\n{findings_count} finding(s).", file=sys.stderr)
        return 0 if result["passed"] else 1
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
