#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

When invoked with ``--json``, the script outputs a single JSON object
to stdout and nothing else. The object has the following shape:

{
    "pass": boolean,   // true if no findings, false otherwise
    "markdown_files_scanned": integer,   // number of markdown files
                                        // processed (non-vendored and existing)
    "links_resolved": integer,   // number of link targets examined
                                 // (after filtering) in the processed files
    "resources_checked": integer,   // number of items returned by discover()
    "files_skipped_as_vendored": integer,   // number of markdown files
                                            // skipped due to being vendored
    "broken_links": [   // array of objects, each representing a broken link
        {
            "file": string,   // path of the markdown file containing
                              // the broken link, relative to repository root
            "line": integer,   // line number in the markdown file (1-indexed)
            "target": string,   // the raw link target as found in the markdown
            "resolved": string   // the absolute resolved path that did not exist
        }
    ],
    "unlinked_resources": [   // array of objects, each representing a
                              // resource not linked from the README
        {
            "file": string,   // path of the resource file, relative to
                              // repository root
            "kind": string,   // the kind of the resource (e.g., "skill", "agent")
            "name": string    // the name of the resource
        }
    ]
}

Without ``--json``, the output and exit code are unchanged from the original behavior.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

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


def check_links(registry: list[dict]) -> tuple[list[str], dict]:
    findings = []
    stats: dict[str, Any] = {
        "markdown_files_processed": 0,
        "markdown_files_skipped_vendored": 0,
        "links_resolved": 0,
        "broken_links_details": [],  # list of dicts
    }
    for md in tracked_markdown():
        if is_vendored(md, registry):
            stats["markdown_files_skipped_vendored"] += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        stats["markdown_files_processed"] += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                stats["links_resolved"] += 1
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    finding = f"{rel}:{line_no}: broken-link -> {target}"
                    findings.append(finding)
                    stats["broken_links_details"].append(
                        {
                            "file": str(rel),
                            "line": line_no,
                            "target": target,
                            "resolved": str((md.parent / bare).resolve()),
                        }
                    )
    return findings, stats


def check_readme_coverage() -> tuple[list[str], dict]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    findings = []
    stats: dict[str, Any] = {
        "resources_checked": len(items),
        "unlinked_resources_details": [],  # list of dicts
    }
    for item in items:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            finding = (
                f"README.md: undocumented -> {item.kind}/{item.name} "
                f"(add a row linking {item.src.relative_to(ROOT).as_posix()})"
            )
            findings.append(finding)
            stats["unlinked_resources_details"].append(
                {
                    "file": item.src.relative_to(ROOT).as_posix(),
                    "kind": item.kind,
                    "name": item.name,
                }
            )
    return findings, stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    findings_link, stats_link = check_links(registry)
    findings_cov, stats_cov = check_readme_coverage()
    findings = findings_link + findings_cov

    if args.json:
        result = {
            "pass": len(findings) == 0,
            "markdown_files_scanned": stats_link["markdown_files_processed"],
            "links_resolved": stats_link["links_resolved"],
            "resources_checked": stats_cov["resources_checked"],
            "files_skipped_as_vendored": stats_link["markdown_files_skipped_vendored"],
            "broken_links": stats_link["broken_links_details"],
            "unlinked_resources": stats_cov["unlinked_resources_details"],
        }
        # Output only JSON to stdout, nothing else
        print(json.dumps(result))
    else:
        for finding in findings:
            print(finding)
        if findings:
            if not args.json:
                print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
