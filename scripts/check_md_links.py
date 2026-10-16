#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

With the --json flag, output a machine-readable JSON object instead of the
human-readable report. The JSON object contains:
- passed: boolean indicating if all checks passed
- markdown_files_scanned: number of markdown files scanned (excluding vendored)
- links_resolved: number of non-skipped links resolved
- resources_checked: number of resources discovered by the CLI
- files_skipped_as_vendored: number of markdown files skipped due to vendored exemption
- broken_links: list of objects, each with:
    - file: relative path of the markdown file containing the broken link
    - line: line number of the broken link
    - target: the raw link target
    - resolved_path: the absolute path that was checked and did not exist
- unlinked_resources: list of objects, each with:
    - kind: the kind of resource (e.g., "agent", "skill")
    - name: the name of the resource
    - src: the source file path relative to the repository root
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
    findings = []
    broken_links = []
    markdown_files_scanned = 0
    links_resolved = 0
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
                links_resolved += 1
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    findings.append(f"{rel}:{line_no}: broken-link -> {target}")
                    broken_links.append(
                        {
                            "file": str(rel),
                            "line": line_no,
                            "target": target,
                            "resolved_path": str((md.parent / bare).resolve()),
                        }
                    )
    return {
        "findings": findings,
        "broken_links": broken_links,
        "markdown_files_scanned": markdown_files_scanned,
        "links_resolved": links_resolved,
        "files_skipped_as_vendored": files_skipped_as_vendored,
    }


def check_readme_coverage() -> dict:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    resources = discover([])
    findings = []
    unlinked_resources = []
    for item in resources:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            rel_src = item.src.relative_to(ROOT).as_posix()
            findings.append(
                f"README.md: undocumented -> {item.kind}/{item.name} (add a row linking {rel_src})"
            )
            unlinked_resources.append({"kind": item.kind, "name": item.name, "src": rel_src})
    return {
        "findings": findings,
        "unlinked_resources": unlinked_resources,
        "resources_checked": len(resources),
    }


def main() -> int:
    # Check for --json flag
    json_mode = "--json" in sys.argv
    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    link_result = check_links(registry)
    coverage_result = check_readme_coverage()
    all_findings = link_result["findings"] + coverage_result["findings"]
    if json_mode:
        result = {
            "passed": len(all_findings) == 0,
            "markdown_files_scanned": link_result["markdown_files_scanned"],
            "links_resolved": link_result["links_resolved"],
            "resources_checked": coverage_result["resources_checked"],
            "files_skipped_as_vendored": link_result["files_skipped_as_vendored"],
            "broken_links": link_result["broken_links"],
            "unlinked_resources": coverage_result["unlinked_resources"],
        }
        # Output compact JSON
        print(json.dumps(result, separators=(",", ":")))
        return 0 if len(all_findings) == 0 else 1
    else:
        for finding in all_findings:
            print(finding)
        if all_findings:
            print(f"\n{len(all_findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
