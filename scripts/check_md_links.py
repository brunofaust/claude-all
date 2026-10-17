#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With `--json`, stdout is one object with `passed`, `counts` (`markdown_files_scanned`,
`links_resolved`, `resources_checked`, `vendored_files_skipped`), `broken_links`
(entries with `file`, `line`, `target`, and `resolved_path`), and
`unlinked_resources` (paths). Scanned files exclude vendored and missing tracked files;
resolved links count checked local relative links that exist.
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
    return [finding for finding, _ in collect_link_results(registry)[0]]


def collect_link_results(
    registry: list[dict],
) -> tuple[list[tuple[str, dict]], dict[str, int]]:
    findings: list[tuple[str, dict]] = []
    scanned = skipped = resolved = 0
    for md in tracked_markdown():
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        if is_vendored(md, registry):
            skipped += 1
            continue
        scanned += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                resolved_path = (md.parent / bare).resolve()
                rel = md.relative_to(ROOT)
                if not resolved_path.exists():
                    findings.append(
                        (
                            f"{rel}:{line_no}: broken-link -> {target}",
                            {
                                "file": rel.as_posix(),
                                "line": line_no,
                                "target": target,
                                "resolved_path": resolved_path.relative_to(ROOT).as_posix()
                                if resolved_path.is_relative_to(ROOT)
                                else str(resolved_path),
                            },
                        )
                    )
                else:
                    resolved += 1
    return findings, {
        "markdown_files_scanned": scanned,
        "links_resolved": resolved,
        "vendored_files_skipped": skipped,
    }


def unlinked_resources(discovered: list) -> list[str]:
    readme = (ROOT / "README.md").read_text()
    return [
        item.src.relative_to(ROOT).as_posix()
        for item in discovered
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme
    ]


def check_readme_coverage() -> list[str]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    discovered = discover([])
    missing = set(unlinked_resources(discovered))
    return [
        f"README.md: undocumented -> {item.kind}/{item.name} "
        f"(add a row linking {item.src.relative_to(ROOT).as_posix()})"
        for item in discovered
        if item.src.relative_to(ROOT).as_posix() in missing
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    link_findings, counts = collect_link_results(registry)
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    discovered = discover([])
    resources = check_readme_coverage()
    findings = [finding for finding, _ in link_findings] + resources
    if args.json_output:
        result = {
            "passed": not findings,
            "counts": {
                **counts,
                "resources_checked": len(discovered),
            },
            "broken_links": [item for _, item in link_findings],
            "unlinked_resources": unlinked_resources(discovered),
        }
        print(json.dumps(result))
    else:
        for finding in findings:
            print(finding)
    if findings:
        if not args.json_output:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
