#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

JSON output mode (--json):
{
    "passed": boolean,
    "counts": {
        "markdown_files_scanned": integer,
        "links_resolved": integer,
        "resources_checked": integer,
        "files_skipped_vendored": integer
    },
    "broken_links": [
    {
        "file": string,   // path relative to repo root
        "line": integer,  // line number in the markdown file
        "target": string, // the link target as found in the markdown
        "resolved_path": string // absolute path that was checked and did not exist
    }
],
    "unlinked_resources": [ string ]   // paths relative to repo root
}
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


def check_links(registry: list[dict]) -> tuple[list[str], dict, list[dict]]:
    human_findings = []
    counts = {"markdown_files_scanned": 0, "links_resolved": 0, "files_skipped_vendored": 0}
    broken_links = []
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
                counts["links_resolved"] += 1
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    human_findings.append(f"{rel}:{line_no}: broken-link -> {target}")
                    broken_links.append(
                        {
                            "file": rel.as_posix(),
                            "line": line_no,
                            "target": target,
                            "resolved_path": (md.parent / bare).resolve().as_posix(),
                        }
                    )
    return human_findings, counts, broken_links


def check_readme_coverage() -> tuple[list[str], int, list[str]]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    resources = discover([])
    resources_checked = len(resources)
    human_findings = []
    unlinked_resources = []
    for item in resources:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            human_findings.append(
                f"README.md: undocumented -> {item.kind}/{item.name} "
                f"(add a row linking {item.src.relative_to(ROOT).as_posix()})"
            )
            unlinked_resources.append(item.src.relative_to(ROOT).as_posix())
    return human_findings, resources_checked, unlinked_resources


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    if args.json:
        human_links, counts_links, broken_links = check_links(registry)
        human_cov, resources_checked, unlinked_resources = check_readme_coverage()
        total_findings = len(broken_links) + len(unlinked_resources)
        data = {
            "passed": total_findings == 0,
            "counts": {
                "markdown_files_scanned": counts_links["markdown_files_scanned"],
                "links_resolved": counts_links["links_resolved"],
                "resources_checked": resources_checked,
                "files_skipped_vendored": counts_links["files_skipped_vendored"],
            },
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }
        print(json.dumps(data))
        if total_findings:
            print(f"\n{total_findings} finding(s).", file=sys.stderr)
            return 1
        return 0
    else:
        human_links, _, _ = check_links(registry)
        human_cov, _, _ = check_readme_coverage()
        findings = human_links + human_cov
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
