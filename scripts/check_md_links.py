#!/usr/bin/env python3
"""Gate: relative markdown links resolve; every resource is linked from the README.

Vendored files are exempt from the link check. Exit 0 when clean, 1 on any finding.
Default output is human-readable. `--json` prints one object on stdout instead:
pass, counts{markdown_scanned, vendored_skipped, links_resolved, resources_checked},
broken_links[{file, line, target, resolved}], unlinked_resources[{kind, name, path}].
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


def scan_links(registry: list[dict]) -> tuple[list[dict], dict[str, int]]:
    def repo_relative(path: Path) -> str:
        try:
            return path.relative_to(ROOT).as_posix()
        except ValueError:
            return path.as_posix()

    broken: list[dict] = []
    counts = {"markdown_scanned": 0, "vendored_skipped": 0, "links_resolved": 0}
    for md in tracked_markdown():
        if is_vendored(md, registry):
            counts["vendored_skipped"] += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        counts["markdown_scanned"] += 1
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
                            "file": md.relative_to(ROOT).as_posix(),
                            "line": line_no,
                            "target": target,
                            "resolved": repo_relative(resolved),
                        }
                    )
    return broken, counts


def find_unlinked() -> tuple[list[dict], int]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    unlinked = []
    for item in items:
        path = item.src.relative_to(ROOT).as_posix()
        if f"]({path})" not in readme:
            unlinked.append({"kind": item.kind, "name": item.name, "path": path})
    return unlinked, len(items)


def check_links(registry: list[dict]) -> list[str]:
    broken, _ = scan_links(registry)
    return [f"{Path(b['file'])}:{b['line']}: broken-link -> {b['target']}" for b in broken]


def check_readme_coverage() -> list[str]:
    unlinked, _ = find_unlinked()
    return [
        f"README.md: undocumented -> {u['kind']}/{u['name']} (add a row linking {u['path']})"
        for u in unlinked
    ]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit one machine-readable JSON object on stdout instead of the report",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    if args.json:
        broken, counts = scan_links(registry)
        unlinked, resources_checked = find_unlinked()
        report = {
            "pass": not (broken or unlinked),
            "counts": {**counts, "resources_checked": resources_checked},
            "broken_links": broken,
            "unlinked_resources": unlinked,
        }
        print(json.dumps(report, indent=2))
        finding_count = len(broken) + len(unlinked)
    else:
        findings = check_links(registry) + check_readme_coverage()
        for finding in findings:
            print(finding)
        finding_count = len(findings)
    if finding_count:
        print(f"\n{finding_count} finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
