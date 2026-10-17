#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With --json flag, emits a single machine-readable JSON object to stdout instead of
the human-formatted report. The JSON shape is:
{
  "passed": bool,                    # True if no findings, False otherwise
  "markdown_files_scanned": int,     # Number of .md files processed
  "links_resolved": int,             # Number of relative links checked
  "resources_checked": int,          # Number of resources checked for README linkage
  "files_skipped_vendored": int,     # Number of vendored .md files skipped
  "broken_links": [                  # List of broken link findings
    {
      "file": str,                   # Path to markdown file containing the link
      "line": int,                   # Line number (1-based)
      "target": str,                 # Raw link target from markdown
      "resolved": str                # Resolved path that did not exist
    }
  ],
  "unlinked_resources": [            # List of resources not linked from README
    {
      "kind": str,                   # e.g., "skill", "agent"
      "name": str,                   # Resource name
      "src": str                     # Path to resource source file
    }
  ]
}
Without --json, output and exit codes are unchanged from today.
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


def format_broken_link(finding: dict) -> str:
    return f"{finding['file']}:{finding['line']}: broken-link -> {finding['target']}"


def format_unlinked_resource(finding: dict) -> str:
    return f"README.md: undocumented -> {finding['kind']}/{finding['name']} (add a row linking {finding['src']})"


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ROOT / p for p in out.split("\0") if p]


def check_links(registry: list[dict]) -> tuple[list[dict], dict]:
    findings = []
    stats = {"markdown_files_scanned": 0, "links_resolved": 0, "files_skipped_vendored": 0}
    for md in tracked_markdown():
        if is_vendored(md, registry):
            stats["files_skipped_vendored"] += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        stats["markdown_files_scanned"] += 1
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
                    findings.append(
                        {
                            "file": str(rel),
                            "line": line_no,
                            "target": target,
                            "resolved": str((md.parent / bare).resolve()),
                        }
                    )
    return findings, stats


def check_readme_coverage() -> tuple[list[dict], dict]:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    findings = []
    for item in discover([]):
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            findings.append(
                {"kind": item.kind, "name": item.name, "src": str(item.src.relative_to(ROOT))}
            )
    stats = {"resources_checked": len(list(discover([])))}
    return findings, stats


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable report",
    )
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    link_findings, link_stats = check_links(registry)
    coverage_findings, coverage_stats = check_readme_coverage()

    findings = link_findings + coverage_findings
    stats = {
        **link_stats,
        **coverage_stats,
        "passed": len(findings) == 0,
        "broken_links": link_findings,
        "unlinked_resources": coverage_findings,
    }

    if args.json:
        print(json.dumps(stats, indent=None, separators=(",", ":")))
    else:
        for finding in findings:
            if "file" in finding:  # broken link finding
                print(format_broken_link(finding))
            else:  # unlinked resource finding
                print(format_unlinked_resource(finding))
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
