#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With --json, emits a machine-readable JSON object instead of the human-readable
report. The JSON schema:

{
  "passed": bool,
  "counts": {
    "markdown_files_scanned": int,
    "links_resolved": int,
    "resources_checked": int,
    "files_skipped_as_vendored": int
  },
  "broken_links": [
    {
      "file": str,      # relative path to markdown file containing the broken link
      "line": int,      # line number (1-indexed)
      "raw_link": str,  # the link target as written in the markdown
      "resolved_path": str  # absolute path that was checked and did not exist
    }
  ],
  "unlinked_resources": [
    {
      "kind": str,      # e.g., "skill", "agent"
      "name": str,      # resource name
      "path": str,      # relative path to the resource's source file
                    # that should be linked in README
    }
  ]
}
Without --json, output and exit codes are unchanged from the original behavior.
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


def _scan_markdown_files(
    registry: list[dict],
) -> tuple[
    list[Path],  # scanned files (non-vendored and existing)
    int,  # number of files skipped as vendored
    list[dict],  # broken links (each dict with file, line, raw_link, resolved_path)
    int,  # number of links resolved (checked)
]:
    scanned_files = []
    skipped_vendored = 0
    broken_links = []
    links_resolved = 0

    for md in tracked_markdown():
        if is_vendored(md, registry):
            skipped_vendored += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        scanned_files.append(md)
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
                            "file": str(rel),
                            "line": line_no,
                            "raw_link": target,
                            "resolved_path": str((md.parent / bare).resolve()),
                        }
                    )
    return scanned_files, skipped_vendored, broken_links, links_resolved


def _check_readme_coverage() -> tuple[list[dict], int]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    resources = []
    all_items = discover([])
    for item in all_items:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            resources.append(
                {"kind": item.kind, "name": item.name, "path": str(item.src.relative_to(ROOT))}
            )
    return resources, len(all_items)


def check_links(registry: list[dict]) -> list[str]:
    """Return human-readable findings for broken links."""
    _, _, broken_links, _ = _scan_markdown_files(registry)
    unlinked_resources, _ = _check_readme_coverage()
    return format_findings(broken_links, unlinked_resources)


def check_readme_coverage() -> list[str]:
    """Return human-readable findings for README coverage."""
    unlinked_resources, _ = _check_readme_coverage()
    return [
        f"README.md: undocumented -> {item['kind']}/{item['name']} "
        f"(add a row linking {item['path']})"
        for item in unlinked_resources
    ]


def format_findings(broken_links: list[dict], unlinked_resources: list[dict]) -> list[str]:
    findings = []
    for bl in broken_links:
        findings.append(f"{bl['file']}:{bl['line']}: broken-link -> {bl['raw_link']}")
    for ur in unlinked_resources:
        findings.append(
            f"README.md: undocumented -> {ur['kind']}/{ur['name']} (add a row linking {ur['path']})"
        )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    scanned_files, skipped_vendored, broken_links, links_resolved = _scan_markdown_files(registry)
    unlinked_resources, resources_checked = _check_readme_coverage()

    if args.json:
        result = {
            "passed": len(broken_links) == 0 and len(unlinked_resources) == 0,
            "counts": {
                "markdown_files_scanned": len(scanned_files),
                "links_resolved": links_resolved,
                "resources_checked": resources_checked,
                "files_skipped_as_vendored": skipped_vendored,
            },
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }
        # Ensure ASCII-safe output for machine readability
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["passed"] else 1
    else:
        findings = format_findings(broken_links, unlinked_resources)
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
