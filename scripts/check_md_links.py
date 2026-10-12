#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With the --json flag, the script outputs a machine-readable JSON object to stdout
with the following shape:
{
    "passed": bool,  # True if no findings, False otherwise
    "counts": {
        "markdown_files_scanned": int,
        "links_resolved": int,
        "resources_checked": int,
        "files_skipped_vendored": int
    },
    "broken_links": [
        {
            "file": str,
            "line": int,
            "target": str,
            "resolved_path": str
        }
    ],
    "unlinked_resources": [
        {
            "path": str
        }
    ]
}
Diagnostics (if any) are written to stderr.
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


def run_checks_structured(registry: list[dict]):
    """Run checks and return structured data and counts.

    Returns a tuple:
        (findings_strings, broken_links, unlinked_resources, counts)
    where:
        findings_strings: list of human-readable strings
            (same as from check_links + check_readme_coverage)
        broken_links: list of dict with keys:
            file (str, relative to ROOT),
            line (int),
            target (str),
            resolved_path (str)
        unlinked_resources: list of dict with keys:
            path (str, relative to ROOT)
        counts: dict with keys:
            markdown_files_scanned (int),
            links_resolved (int),
            resources_checked (int),
            files_skipped_vendored (int)
    """
    findings_strings = []
    broken_links = []
    unlinked_resources = []
    counts = {
        "markdown_files_scanned": 0,
        "links_resolved": 0,
        "resources_checked": 0,
        "files_skipped_vendored": 0,
    }

    # First, get all tracked markdown files
    all_md = tracked_markdown()
    # Count vendored files
    for md in all_md:
        if is_vendored(md, registry):
            counts["files_skipped_vendored"] += 1

    # Now process non-vendored files for links
    for md in all_md:
        if is_vendored(md, registry):
            continue
        if not md.exists():
            # Skip missing files (tracked but deleted)
            continue
        counts["markdown_files_scanned"] += 1
        try:
            text = md.read_text()
        except Exception:
            # If we can't read the file, skip it (shouldn't happen if it exists)
            continue
        for line_no, line in strip_code_blocks(text):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                counts["links_resolved"] += 1
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    findings_strings.append(f"{rel}:{line_no}: broken-link -> {target}")
                    broken_links.append(
                        {
                            "file": str(rel),
                            "line": line_no,
                            "target": target,
                            "resolved_path": str((md.parent / bare).resolve()),
                        }
                    )

    # Now check README coverage
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    resources = discover([])
    counts["resources_checked"] = len(resources)
    readme = (ROOT / "README.md").read_text()
    for item in resources:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            rel_path = item.src.relative_to(ROOT).as_posix()
            findings_strings.append(
                f"README.md: undocumented -> {item.kind}/{item.name} (add a row linking {rel_path})"
            )
            unlinked_resources.append(
                {
                    "path": rel_path,
                }
            )

    return findings_strings, broken_links, unlinked_resources, counts


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args, _ = parser.parse_known_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    if args.json:
        findings_strings, broken_links, unlinked_resources, counts = run_checks_structured(registry)
        result = {
            "passed": len(findings_strings) == 0,
            "counts": counts,
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }
        # Output only JSON to stdout
        json.dump(result, sys.stdout)
        # Add a newline for consistency with typical JSON tools
        print()
        # Exit code: 0 if passed, 1 if not
        return 0 if result["passed"] else 1
    else:
        # Default behavior: human-readable output
        findings = check_links(registry) + check_readme_coverage()
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
