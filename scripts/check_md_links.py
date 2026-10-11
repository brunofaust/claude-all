#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

JSON output mode:
    --json: emit a single machine-readable JSON object to stdout instead of the
    human-formatted report. The JSON object contains:
        - pass: boolean indicating overall success (True if no broken links and
          no unlinked resources)
        - markdown_files_scanned: number of markdown files returned by
          tracked_markdown() (all *.md files tracked by git)
        - links_resolved: number of link targets examined for existence (after
          skipping images, absolute URLs, anchors, mailto, and after removing
          fragment, and having a non-empty bare target)
        - resources_checked: number of items returned by discover([]) (total
          number of resources checked for being linked in the README)
        - files_skipped_as_vendored: number of markdown files from
          tracked_markdown() that were skipped due to being vendored (where
          is_vendored() returned True)
        - broken_links: list of objects, each representing a broken link with:
            - file: string (relative path of the markdown file containing the
              broken link)
            - line_no: integer (line number in the markdown file)
            - link_target: string (raw link target from the markdown)
            - resolved_path: string (absolute path that was checked and did not
              exist)
        - unlinked_resources: list of objects, each representing an unlinked
          resource with:
            - path: string (resource path relative to the repository root)
            - kind: string (resource kind, e.g., "skill")
            - name: string (resource name, e.g., "python-style")

    Without --json, output and exit codes are unchanged from today.
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


def check_links_structured(registry: list[dict]) -> tuple[list[dict], int, int, int]:
    """Return (broken_links, markdown_files_scanned, links_resolved, files_skipped_as_vendored).
    Each broken link is a dict with keys: file, line_no, link_target, resolved_path.
    """
    broken_links = []
    markdown_files = tracked_markdown()
    markdown_files_scanned = len(markdown_files)
    links_resolved = 0
    files_skipped_as_vendored = 0

    for md in markdown_files:
        if is_vendored(md, registry):
            files_skipped_as_vendored += 1
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
                links_resolved += 1
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    broken_links.append(
                        {
                            "file": str(rel),
                            "line_no": line_no,
                            "link_target": target,
                            "resolved_path": str((md.parent / bare).resolve()),
                        }
                    )
    return broken_links, markdown_files_scanned, links_resolved, files_skipped_as_vendored


def check_links(registry: list[dict]) -> list[str]:
    """Return human-readable findings for broken links (for backward compatibility)."""
    broken_links, _, _, _ = check_links_structured(registry)
    return [
        f"{link['file']}:{link['line_no']}: broken-link -> {link['link_target']}"
        for link in broken_links
    ]


def check_readme_coverage_structured() -> tuple[list[dict], int]:
    """Return (unlinked_resources, resources_checked).
    Each unlinked resource is a dict with keys: path, kind, name.
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    resources = discover([])
    resources_checked = len(resources)
    unlinked_resources = []
    for item in resources:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            unlinked_resources.append(
                {
                    "path": item.src.relative_to(ROOT).as_posix(),
                    "kind": item.kind,
                    "name": item.name,
                }
            )
    return unlinked_resources, resources_checked


def check_readme_coverage() -> list[str]:
    """Return human-readable findings for README coverage (for backward compatibility)."""
    unlinked_resources, _ = check_readme_coverage_structured()
    return [
        f"README.md: undocumented -> {item['kind']}/{item['name']} "
        f"(add a row linking {item['path']})"
        for item in unlinked_resources
    ]


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
        broken_links, mds_scanned, links_resolved, vendored_skipped = check_links_structured(
            registry
        )
        unlinked_resources, resources_checked = check_readme_coverage_structured()
    except Exception:
        # Let the exception go to stderr (as currently) and exit with non-zero.
        raise

    data = {
        "pass": not broken_links and not unlinked_resources,
        "markdown_files_scanned": mds_scanned,
        "links_resolved": links_resolved,
        "resources_checked": resources_checked,
        "files_skipped_as_vendored": vendored_skipped,
        "broken_links": broken_links,
        "unlinked_resources": unlinked_resources,
    }

    if args.json:
        # Output compact JSON to stdout, nothing else.
        print(json.dumps(data, separators=(",", ":")))
        return 0 if data["pass"] else 1
    else:
        # Human-readable output: same as before.
        findings = check_links(registry) + check_readme_coverage()
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
