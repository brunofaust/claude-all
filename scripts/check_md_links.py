#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With --json flag, outputs a machine-readable object:
{
    "pass": boolean,                    # True if no findings, False otherwise
    "markdown_files_scanned": int,      # Number of .md files scanned (excluding vendored)
    "links_resolved": int,              # Number of relative markdown links checked
    "resources_checked": int,           # Number of resources discovered for README check
    "files_skipped_as_vendored": int,   # Number of vendored .md files skipped
    "broken_links": [                   # Details for each broken link
        {
            "file": string,             # Relative file path and line number (e.g. "docs/skill.md:42")
            "raw_target": string,       # The link target as written in the markdown
            "resolved_path": string     # The resolved path that did not exist
        }
    ],
    "unlinked_resources": [string]      # List of resource paths not linked from README
}
Without --json, output is human-readable text (existing behavior).
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


def check_links(registry: list[dict]) -> dict:
    findings = []  # each will be a dict with keys: file (str relative to ROOT), line (int), raw_target (str), resolved_path (str)
    links_checked = 0
    markdown_files_scanned = 0
    files_skipped_as_vendored = 0
    for md in tracked_markdown():
        if is_vendored(md, registry):
            files_skipped_as_vendored += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        markdown_files_scanned += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                links_checked += 1
                target_path = (md.parent / bare).resolve()
                if not target_path.exists():
                    rel = md.relative_to(ROOT)
                    findings.append(
                        {
                            "file": rel.as_posix(),
                            "line": line_no,
                            "raw_target": target,
                            "resolved_path": target_path.as_posix(),
                        }
                    )
    return {
        "findings": findings,
        "links_checked": links_checked,
        "markdown_files_scanned": markdown_files_scanned,
        "files_skipped_as_vendored": files_skipped_as_vendored,
    }


def check_readme_coverage() -> dict:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    findings = [
        f"README.md: undocumented -> {item.kind}/{item.name} "
        f"(add a row linking {item.src.relative_to(ROOT).as_posix()})"
        for item in discover([])
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme
    ]
    return {
        "findings": findings,
        "resources_checked": len(list(discover([]))),
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    links_result = check_links(registry)
    readme_result = check_readme_coverage()

    if args.json:
        # JSON output mode
        broken_links = []
        for f in links_result["findings"]:
            broken_links.append(
                {
                    "file": f"{f['file']}:{f['line']}",
                    "raw_target": f["raw_target"],
                    "resolved_path": f["resolved_path"],
                }
            )

        unlinked_resources = []
        for finding in readme_result["findings"]:
            # Format is: "README.md: undocumented -> kind/name (add a row linking path)"
            # We want to extract the path part
            if "(add a row linking " in finding:
                path_part = finding.split("(add a row linking ")[1].rstrip(")")
                unlinked_resources.append(path_part)
            else:
                unlinked_resources.append(finding)

        result = {
            "pass": len(links_result["findings"]) == 0 and len(readme_result["findings"]) == 0,
            "markdown_files_scanned": links_result["markdown_files_scanned"],
            "links_resolved": links_result["links_checked"],
            "resources_checked": readme_result["resources_checked"],
            "files_skipped_as_vendored": links_result["files_skipped_as_vendored"],
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }

        print(json.dumps(result))
        # Return appropriate exit code
        if len(links_result["findings"]) > 0 or len(readme_result["findings"]) > 0:
            return 1
        return 0
    else:
        # Human-readable output (existing behavior)
        # Convert link findings to strings
        link_findings_strings = [
            f"{f['file']}:{f['line']}: broken-link -> {f['raw_target']}"
            for f in links_result["findings"]
        ]
        all_findings = link_findings_strings + readme_result["findings"]
        for finding in all_findings:
            print(finding)
        if all_findings:
            print(f"\n{len(all_findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
