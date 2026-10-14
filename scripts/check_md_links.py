#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

When --json is specified, emits a single JSON object to stdout with the following shape:
{
  "passed": boolean,                    # True if no broken links and no unlinked resources
  "counts": {
    "markdown_files_scanned": int,      # Number of Markdown files processed
                                        # (excluding vendored and missing)
    "links_resolved": int,              # Number of link targets checked
                                        # (excluding skipped prefixes and anchors)
    "resources_checked": int,           # Number of resources discovered by
                                        # claude-all discover
    "files_skipped_as_vendored": int    # Number of Markdown files skipped due
                                        # to vendored exemption
  },
  "broken_links": [                     # Each broken link
    {
      "file": string,                   # Path of Markdown file containing the
                                        # link, relative to repo root
      "line": int,                      # Line number in the file (1-indexed)
      "target": string,                 # The raw link target as found in the
                                        # Markdown
      "resolved_path": string           # The absolute resolved path that did not
                                        # exist
    }
  ],
  "unlinked_resources": [               # Each resource not linked from README
    string                              # Path of the resource relative to repo
                                        # root (e.g., "src/claude_all/skills/generic/prek/SKILL.md")
  ]
}
Diagnostics (if any) are printed to stderr. Without --json, behavior is unchanged.
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


def check_links_structured(registry: list[dict]):
    """Return (scanned_files, links_resolved, broken_links, skipped_vendored) for JSON mode."""
    scanned_files = 0
    links_resolved = 0
    broken_links = []  # each will be dict with file, line, target, resolved_path
    skipped_vendored = 0
    for md in tracked_markdown():
        if is_vendored(md, registry):
            skipped_vendored += 1
            continue
        if not md.exists():
            continue
        scanned_files += 1
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
                            "file": md,
                            "line": line_no,
                            "target": target,
                            "resolved_path": (md.parent / bare).resolve(),
                        }
                    )
    return scanned_files, links_resolved, broken_links, skipped_vendored


def check_readme_coverage_structured():
    """Return (resources_checked, unlinked_resources) for JSON mode."""
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    resources = discover([])
    resources_checked = len(resources)
    unlinked_resources = []
    for item in resources:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            unlinked_resources.append(item.src.relative_to(ROOT).as_posix())
    return resources_checked, unlinked_resources


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--json", action="store_true")
    args, unknown = parser.parse_known_args()
    if unknown:
        # If there are unknown arguments, we ignore them for now but could error.
        # For simplicity, we just ignore and let the existing behavior handle them?
        # But the existing behavior doesn't take any arguments, so we should error.
        # However, to keep changes minimal, we just ignore extra args.
        pass

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    if args.json:
        scanned_files, links_resolved, broken_links, skipped_vendored = check_links_structured(
            registry
        )
        resources_checked, unlinked_resources = check_readme_coverage_structured()

        passed = len(broken_links) == 0 and len(unlinked_resources) == 0
        result = {
            "passed": passed,
            "counts": {
                "markdown_files_scanned": scanned_files,
                "links_resolved": links_resolved,
                "resources_checked": resources_checked,
                "files_skipped_as_vendored": skipped_vendored,
            },
            "broken_links": [
                {
                    "file": str(link["file"].relative_to(ROOT)),
                    "line": link["line"],
                    "target": link["target"],
                    "resolved_path": str(link["resolved_path"]),
                }
                for link in broken_links
            ],
            "unlinked_resources": unlinked_resources,
        }
        print(json.dumps(result))
        if not passed:
            print(f"\n{len(broken_links) + len(unlinked_resources)} finding(s).", file=sys.stderr)
            return 1
        return 0
    else:
        # Human mode: unchanged behavior
        findings = check_links(registry) + check_readme_coverage()
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
