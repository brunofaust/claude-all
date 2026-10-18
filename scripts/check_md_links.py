#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

Usage:
    python3 scripts/check_md_links.py          human-readable findings on stdout
    python3 scripts/check_md_links.py --json   one JSON object on stdout, nothing else

Exit code is the same in both modes: 0 when there are no findings, 1 otherwise.
The "N finding(s)." diagnostic goes to stderr in both modes.

JSON output (`schema_version` 1):

    {
      "schema_version": 1,
      "passed": true,                      # false when any finding exists
      "counts": {
        "markdown_files_scanned": 0,       # tracked .md files read by the link check
        "files_skipped_vendored": 0,       # tracked .md files exempted as vendored
        "links_checked": 0,                # link targets evaluated (see below)
        "links_resolved": 0,               # of those, targets that exist
        "resources_checked": 0             # discovered resources checked for a README row
      },
      "broken_links": [
        {"file": "docs/a.md",              # repo-relative POSIX path of the containing file
         "line": 3,                        # 1-based line of the link in that file
         "target": "../nope.md#x",         # raw target exactly as written, incl. any #anchor
         "resolved_path": "nope.md"}       # repo-relative POSIX path that does not exist
      ],
      "unlinked_resources": [
        {"kind": "skills",                 # resource kind from discover()
         "name": "my-skill",
         "path": "src/claude_all/skills/generic/my-skill/SKILL.md"}  # src, repo-relative POSIX
      ]
    }

Counting semantics:
- markdown_files_scanned: tracked `*.md` files that were read. Vendored files and
  tracked-but-deleted files are not counted.
- files_skipped_vendored: tracked `*.md` files exempted by `is_vendored`.
- links_checked: link targets evaluated. Anchors, `http(s)://`, `mailto:`, `tel:` and
  `/`-prefixed targets are not counted.
- links_resolved: the subset of links_checked whose target path exists.
- resources_checked: `len(discover([]))`, the resources the README coverage check covers.

Paths are repo-relative POSIX strings, so output is identical on a developer machine and
in CI. A link that escapes the repository keeps its absolute POSIX path in resolved_path.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1

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


def repo_posix(path: Path) -> str:
    """Repo-relative POSIX path; falls back to the absolute POSIX path outside the repo."""
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def scan_links(registry: list[dict]) -> tuple[dict[str, int], list[dict]]:
    counts = {
        "markdown_files_scanned": 0,
        "files_skipped_vendored": 0,
        "links_checked": 0,
        "links_resolved": 0,
    }
    broken: list[dict] = []
    for md in tracked_markdown():
        if is_vendored(md, registry):
            counts["files_skipped_vendored"] += 1
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
                counts["links_checked"] += 1
                resolved = (md.parent / bare).resolve()
                if resolved.exists():
                    counts["links_resolved"] += 1
                else:
                    broken.append(
                        {
                            "file": repo_posix(md),
                            "line": line_no,
                            "target": target,
                            "resolved_path": repo_posix(resolved),
                        }
                    )
    return counts, broken


def format_broken_link(record: dict) -> str:
    # str(Path) keeps the native separator the human report has always used.
    return f"{Path(record['file'])}:{record['line']}: broken-link -> {record['target']}"


def format_unlinked(record: dict) -> str:
    return (
        f"README.md: undocumented -> {record['kind']}/{record['name']} "
        f"(add a row linking {record['path']})"
    )


def check_links(registry: list[dict]) -> list[str]:
    _, broken = scan_links(registry)
    return [format_broken_link(b) for b in broken]


def readme_coverage() -> tuple[int, list[dict]]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    unlinked = [
        {"kind": item.kind, "name": item.name, "path": repo_posix(item.src)}
        for item in items
        if f"]({repo_posix(item.src)})" not in readme
    ]
    return len(items), unlinked


def check_readme_coverage() -> list[str]:
    return [format_unlinked(u) for u in readme_coverage()[1]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check markdown links and README coverage.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a single machine-readable JSON object on stdout instead of the report",
    )
    args = parser.parse_args(argv)

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    link_counts, broken = scan_links(registry)
    resources_checked, unlinked = readme_coverage()
    finding_count = len(broken) + len(unlinked)

    if args.json:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "passed": finding_count == 0,
            "counts": {**link_counts, "resources_checked": resources_checked},
            "broken_links": broken,
            "unlinked_resources": unlinked,
        }
        print(json.dumps(payload, indent=2))
    else:
        for finding in [format_broken_link(b) for b in broken] + [
            format_unlinked(u) for u in unlinked
        ]:
            print(finding)

    if finding_count:
        print(f"\n{finding_count} finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
