#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With --json flag:
  Emits a machine-readable JSON object to stdout with the following shape:
  {
    "pass": bool,                        # True if no issues
    "markdown_files_scanned": int,       # Count of .md files from git ls-files
    "links_resolved": int,               # Number of link targets checked
    "resources_checked": int,            # Number of resources discovered
    "files_skipped_as_vendored": int,    # Count of vendored .md files skipped
    "broken_links": [                    # List of broken relative links
      {
        "file": str,                     # Markdown file containing the link (repo-relative)
        "line": int,                     # Line number in the markdown file
        "link_target": str,              # Raw link target from markdown
        "resolved_path": str             # Resolved path (repo-relative) that does not exist
      }
    ],
    "unlinked_resources": [              # List of resource paths not linked from README
      str                                # Resource path (relative to repo root)
    ]
  }
  Exit code is 0 if pass is True, 1 otherwise.
  Diagnostics (if any) are written to stderr.

Without --json flag:
  Outputs human-readable findings (one per line) to stdout, followed by a count
  of findings to stderr. Exit code is 0 if no findings, 1 otherwise.
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


def check_links(registry: list[dict]) -> tuple[list[dict], int, int, int]:
    findings = []  # will be list of dicts for broken links
    links_examined = 0
    files_scanned = 0
    files_skipped = 0

    markdown_files = tracked_markdown()
    files_scanned = len(markdown_files)

    for md in markdown_files:
        if is_vendored(md, registry):
            files_skipped += 1
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
                links_examined += 1
                resolved = (md.parent / bare).resolve()
                if not resolved.exists():
                    rel_md = md.relative_to(ROOT)
                    findings.append(
                        {
                            "file": str(rel_md),
                            "line": line_no,
                            "link_target": target,
                            "resolved_path": str(resolved.relative_to(ROOT)),
                        }
                    )
    return findings, links_examined, files_scanned, files_skipped


def check_readme_coverage() -> tuple[list[dict], int]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    unlinked = []
    for item in items:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            unlinked.append(
                {
                    "kind": item.kind,
                    "name": item.name,
                    "path": item.src.relative_to(ROOT).as_posix(),
                }
            )
    return unlinked, len(items)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json", action="store_true", help="Output JSON instead of human-readable format"
    )
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    broken_links, links_examined, files_scanned, files_skipped = check_links(registry)
    unlinked_resources, resources_checked = check_readme_coverage()

    if args.json:
        result = {
            "pass": len(broken_links) == 0 and len(unlinked_resources) == 0,
            "markdown_files_scanned": files_scanned,
            "links_resolved": links_examined,
            "resources_checked": resources_checked,
            "files_skipped_as_vendored": files_skipped,
            "broken_links": broken_links,
            "unlinked_resources": [r["path"] for r in unlinked_resources],
        }
        print(json.dumps(result))
        sys.exit(0 if result["pass"] else 1)
    else:
        # Output human-readable format
        for link in broken_links:
            print(f"{link['file']}:{link['line']}: broken-link -> {link['link_target']}")
        for resource in unlinked_resources:
            print(
                f"README.md: undocumented -> {resource['kind']}/{resource['name']} "
                f"(add a row linking {resource['path']})"
            )
        if broken_links or unlinked_resources:
            print(f"\n{len(broken_links) + len(unlinked_resources)} finding(s).", file=sys.stderr)
            sys.exit(1)
        else:
            sys.exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
