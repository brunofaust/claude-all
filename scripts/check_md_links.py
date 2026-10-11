#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.
Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With --json, outputs a JSON object with the following keys:
  - passed: boolean indicating if all checks passed
  - counts: an object with:
      - markdown_files_scanned: number of markdown files processed for link checking
      - links_resolved: number of non-skipped links checked
      - resources_checked: number of items discovered for README coverage
      - files_skipped_as_vendored: number of markdown files skipped due to vendoring
  - broken_links: array of objects, each representing a broken link with:
      - file: path of the markdown file containing the link, relative to repository root
      - line: line number (1-indexed) where the link occurs
      - raw_link_target: the link target as found in the markdown
      - resolved_path: the absolute path checked (did not exist)
  - unlinked_resources: array of objects, each representing an unlinked resource, with:
      - path: path of the resource relative to repository root
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


def _check_links_and_collect(registry: list[dict]):
    findings = []
    metrics = {
        "markdown_files_scanned": 0,
        "links_resolved": 0,
        "files_skipped_as_vendored": 0,
    }
    broken_links = []

    markdown_files = tracked_markdown()
    vendored_count = 0
    for md in markdown_files:
        if is_vendored(md, registry):
            vendored_count += 1
            continue
        if not md.exists():
            continue
        metrics["markdown_files_scanned"] += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                metrics["links_resolved"] += 1
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    findings.append(f"{rel}:{line_no}: broken-link -> {target}")
                    broken_links.append(
                        {
                            "file": str(rel),
                            "line": line_no,
                            "raw_link_target": target,
                            "resolved_path": str((md.parent / bare).resolve()),
                        }
                    )
    metrics["files_skipped_as_vendored"] = vendored_count
    return findings, metrics, broken_links


def _check_readme_coverage_and_collect():
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    findings = []
    metrics = {
        "resources_checked": 0,
    }
    unlinked_resources = []

    items = discover([])
    metrics["resources_checked"] = len(items)
    for item in items:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            rel_path = item.src.relative_to(ROOT).as_posix()
            findings.append(
                f"README.md: undocumented -> {item.kind}/{item.name} (add a row linking {rel_path})"
            )
            unlinked_resources.append(
                {
                    "path": rel_path,
                }
            )
    return findings, metrics, unlinked_resources


def check_links(registry: list[dict]) -> list[str]:
    findings, _, _ = _check_links_and_collect(registry)
    return findings


def check_readme_coverage() -> list[str]:
    findings, _, _ = _check_readme_coverage_and_collect()
    return findings


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    if args.json:
        findings_link, metrics_link, broken_links = _check_links_and_collect(registry)
        findings_coverage, metrics_coverage, unlinked_resources = (
            _check_readme_coverage_and_collect()
        )
        # Combine metrics
        all_metrics = {
            "markdown_files_scanned": metrics_link["markdown_files_scanned"],
            "links_resolved": metrics_link["links_resolved"],
            "resources_checked": metrics_coverage["resources_checked"],
            "files_skipped_as_vendored": metrics_link["files_skipped_as_vendored"],
        }
        # Build the JSON object
        result = {
            "passed": len(findings_link) + len(findings_coverage) == 0,
            "counts": all_metrics,
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }
        print(json.dumps(result))
        # Exit code: 0 if passed, else 1
        return 0 if result["passed"] else 1
    else:
        findings = check_links(registry) + check_readme_coverage()
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
