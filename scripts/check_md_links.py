#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

Usage:
    python3 scripts/check_md_links.py          human-readable findings on stdout
    python3 scripts/check_md_links.py --json   one JSON object on stdout, nothing else

Both modes exit 1 when there is any finding and 0 otherwise.

JSON shape (`--json`), field names are stable:

    {
      "pass": bool,                      # true when there are no findings
      "counts": {
        "markdown_files_scanned": int,   # tracked, non-vendored .md files whose links were read
        "links_resolved": int,           # relative link targets that exist on disk
        "resources_checked": int,        # discovered resources checked against the README
        "vendored_files_skipped": int    # tracked .md files exempt as vendored
      },
      "broken_links": [                  # rule 1: relative markdown links that do not resolve
        {"file": str, "line": int, "target": str, "resolved": str}
      ],
      "unlinked_resources": [            # rule 2: discovered resources with no README link
        {"kind": str, "name": str, "path": str}
      ]
    }

`file` and `path` are repo-relative POSIX paths; `resolved` is the repo-relative
POSIX path the target resolved to (absolute when it lies outside the repo).
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


def display_path(path: Path) -> str:
    """Repo-relative POSIX path, or the absolute POSIX path when outside the repo."""
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def check_links(registry: list[dict]) -> tuple[list[dict], dict[str, int]]:
    broken: list[dict] = []
    counts = {"markdown_files_scanned": 0, "links_resolved": 0, "vendored_files_skipped": 0}
    for md in tracked_markdown():
        if is_vendored(md, registry):
            counts["vendored_files_skipped"] += 1
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
                resolved = (md.parent / bare).resolve()
                if resolved.exists():
                    counts["links_resolved"] += 1
                else:
                    broken.append(
                        {
                            "file": display_path(md),
                            "line": line_no,
                            "target": target,
                            "resolved": display_path(resolved),
                        }
                    )
    return broken, counts


def check_readme_coverage() -> tuple[list[dict], int]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    unlinked = [
        {
            "kind": item.kind,
            "name": item.name,
            "path": item.src.relative_to(ROOT).as_posix(),
        }
        for item in items
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme
    ]
    return unlinked, len(items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check markdown links and README coverage.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a single machine-readable JSON object on stdout instead of the report",
    )
    args = parser.parse_args(argv)

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    broken, counts = check_links(registry)
    unlinked, resources_checked = check_readme_coverage()
    findings = len(broken) + len(unlinked)

    if args.json:
        report = {
            "pass": findings == 0,
            "counts": {
                "markdown_files_scanned": counts["markdown_files_scanned"],
                "links_resolved": counts["links_resolved"],
                "resources_checked": resources_checked,
                "vendored_files_skipped": counts["vendored_files_skipped"],
            },
            "broken_links": broken,
            "unlinked_resources": unlinked,
        }
        print(json.dumps(report, indent=2))
        return 1 if findings else 0

    for item in broken:
        print(f"{item['file']}:{item['line']}: broken-link -> {item['target']}")
    for item in unlinked:
        print(
            f"README.md: undocumented -> {item['kind']}/{item['name']} "
            f"(add a row linking {item['path']})"
        )
    if findings:
        print(f"\n{findings} finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
