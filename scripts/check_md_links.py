#!/usr/bin/env python3
"""Gate: relative markdown links resolve, and every resource is linked from the README.

Two failures this repo has actually shipped, now mechanical:

1. **Broken relative links.** Four cross-skill links went out one `../` short —
   one of them in an already-merged PR — because nothing checked them. A link is
   only as good as the last rename.
2. **A resource with no README row.** CLAUDE.md says "a PR without a README update
   is incomplete", but prose does not enforce itself. The README tables link to
   each resource's source file, so "is it linked?" is a proxy for "is it documented?"
   that a checker can actually answer.

Vendored files are exempt from check 1: they are kept byte-identical to upstream,
so their upstream-relative links legitimately do not resolve in this tree. Files
listed under a vendored entry's `local_only` are OURS and stay checked.

JSON output (--json):
The script can be run with --json to emit a single machine-readable object to stdout.
Human output remains the default. The JSON shape is:

{
  "passed": bool,
  "markdown_files_scanned": int,
  "links_checked": int,
  "resources_checked": int,
  "vendored_files_skipped": int,
  "broken_links": [
    {"file": "path/to/file.md", "target": "relative/target.md", "resolved_path": "path/to/resolved"}
  ],
  "unlinked_resources": [
    "path/to/resource"
  ]
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
    """Upstream-owned files are exempt: kept byte-identical, so their own relative
    links point at an upstream tree we deliberately did not copy. `local_only`
    files live in the same directory but are OURS — they stay checked.

    Args:
        path: The markdown file being considered.
        registry: The `vendored` entries from `vendored.json`.
    """
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
    """Numbered lines with fenced code removed — a regex or an llms.txt sample
    inside a fenced block only looks like a link.

    Args:
        text: Full markdown source of one file.
    """
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


def _collect_link_data(registry: list[dict]):
    markdown_files_scanned = 0
    vendored_files_skipped = 0
    links_checked = 0
    broken = []
    for md in tracked_markdown():
        if is_vendored(md, registry):
            vendored_files_skipped += 1
            continue
        if not md.exists():
            continue
        markdown_files_scanned += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            cleaned = CODE_SPAN.sub("", line)
            for target in LINK.findall(cleaned):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue
                links_checked += 1
                resolved = (md.parent / bare).resolve()
                if not resolved.exists():
                    rel_file = md.relative_to(ROOT).as_posix()
                    try:
                        resolved_rel = resolved.relative_to(ROOT).as_posix()
                    except ValueError:
                        resolved_rel = str(resolved)
                    broken.append(
                        {
                            "file": rel_file,
                            "target": target,
                            "resolved_path": resolved_rel,
                            "line_no": line_no,
                        }
                    )
    findings = [f"{b['file']}:{b['line_no']}: broken-link -> {b['target']}" for b in broken]
    meta = {
        "markdown_files_scanned": markdown_files_scanned,
        "vendored_files_skipped": vendored_files_skipped,
        "links_checked": links_checked,
        "broken_links": broken,
    }
    return findings, meta


def check_links(registry: list[dict]) -> list[str]:
    findings, _ = _collect_link_data(registry)
    return findings


def _collect_readme_data():
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    resources_checked = len(items)
    unlinked = []
    findings = []
    for item in items:
        rel_path = item.src.relative_to(ROOT).as_posix()
        if f"]({rel_path})" not in readme:
            unlinked.append(
                {
                    "kind": item.kind,
                    "name": item.name,
                    "path": rel_path,
                }
            )
            findings.append(
                f"README.md: undocumented -> {item.kind}/{item.name} (add a row linking {rel_path})"
            )
    meta = {
        "resources_checked": resources_checked,
        "unlinked_resources": unlinked,
    }
    return findings, meta


def check_readme_coverage() -> list[str]:
    findings, _ = _collect_readme_data()
    return findings


def main() -> int:
    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    json_mode = "--json" in sys.argv
    link_findings, link_meta = _collect_link_data(registry)
    readme_findings, readme_meta = _collect_readme_data()
    findings = link_findings + readme_findings
    if json_mode:
        output = {
            "passed": not findings,
            "markdown_files_scanned": link_meta["markdown_files_scanned"],
            "links_checked": link_meta["links_checked"],
            "resources_checked": readme_meta["resources_checked"],
            "vendored_files_skipped": link_meta["vendored_files_skipped"],
            "broken_links": [
                {"file": b["file"], "target": b["target"], "resolved_path": b["resolved_path"]}
                for b in link_meta["broken_links"]
            ],
            "unlinked_resources": [u["path"] for u in readme_meta["unlinked_resources"]],
        }
        print(json.dumps(output))
        return 0 if not findings else 1
    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
