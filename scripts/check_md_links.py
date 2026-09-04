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

With the `--json` flag, the script emits a single machine-readable JSON object to
stdout instead of the human-formatted report. The JSON contains:

* `pass`: boolean indicating overall pass/fail
* `resources_checked`: number of resources checked for README coverage
    * `files_skipped_as_vendored`: number of files skipped due to vendored exemption
* `broken_links`: array of objects, each with:
    - `file`: containing file (relative to repository root)
    - `target`: raw link target as written in the markdown
    - `resolved_path`: the resolved path that did not exist
      (relative to repository root if possible, otherwise absolute)
* `unlinked_resources`: array of strings
    each being the path of a resource not linked from the README
    (relative to repository root)

Human output stays the default and stays byte-identical — this is additive.
Diagnostics, if any, go to stderr.
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


def _get_links_data(registry: list[dict]) -> dict:
    """Compute link check data for JSON output.

    Returns a dict with:
        markdown_files_scanned: int
        links_resolved: int
        files_skipped_as_vendored: int
        broken_links: list of dicts with keys: file, target, resolved_path
    """
    markdown_files = list(tracked_markdown())
    markdown_files_scanned = len(markdown_files)

    links_resolved = 0
    broken_links = []
    files_skipped_as_vendored = 0

    for md in markdown_files:
        if is_vendored(md, registry):
            files_skipped_as_vendored += 1
            continue
        if not md.exists():
            continue
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                links_resolved += 1
                resolved = (md.parent / bare).resolve()
                if not resolved.exists():
                    rel = md.relative_to(ROOT)
                    try:
                        resolved_path_str = str(resolved.relative_to(ROOT))
                    except ValueError:
                        # If the resolved path is not under ROOT, use the absolute path
                        resolved_path_str = str(resolved)
                    broken_links.append(
                        {"file": str(rel), "target": target, "resolved_path": resolved_path_str}
                    )

    return {
        "markdown_files_scanned": markdown_files_scanned,
        "links_resolved": links_resolved,
        "broken_links": broken_links,
        "files_skipped_as_vendored": files_skipped_as_vendored,
    }


def _get_readme_data() -> dict:
    """Compute README coverage data for JSON output.

    Returns a dict with:
        resources_checked: int
        unlinked_resources: list of strings (paths relative to repository root)
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    unlinked_resources = []
    for item in items:
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            unlinked_resources.append(item.src.relative_to(ROOT).as_posix())

    resources_checked = len(items)

    return {"resources_checked": resources_checked, "unlinked_resources": unlinked_resources}


def check_links(registry: list[dict]) -> list[str]:
    """Return a list of human-readable strings for broken links.

    Each string is formatted as:
        "{relative_file}:{line_number}: broken-link -> {raw_target}"
    """
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
    """Return a list of human-readable strings for unlinked resources.

    Each string is formatted as:
        "README.md: undocumented -> {kind}/{name} (add a row linking {src})"
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    return [
        f"README.md: undocumented -> {item.kind}/{item.name} "
        f"(add a row linking {item.src.relative_to(ROOT).as_posix()})"
        for item in discover([])
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme
    ]


def main() -> int:
    # Check for --json flag
    json_mode = False
    if len(sys.argv) > 1 and sys.argv[1] == "--json":
        json_mode = True

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    if json_mode:
        # Compute JSON data using helper functions
        links_data = _get_links_data(registry)
        readme_data = _get_readme_data()
        pass_ = len(links_data["broken_links"]) == 0 and len(readme_data["unlinked_resources"]) == 0
        counts = {
            "markdown_files_scanned": links_data["markdown_files_scanned"],
            "links_resolved": links_data["links_resolved"],
            "resources_checked": readme_data["resources_checked"],
            "files_skipped_as_vendored": links_data["files_skipped_as_vendored"],
        }
        result = {
            "pass": pass_,
            "counts": counts,
            "broken_links": links_data["broken_links"],
            "unlinked_resources": readme_data["unlinked_resources"],
        }
        print(json.dumps(result))
        return 0 if pass_ else 1
    else:
        # Original behavior
        findings = check_links(registry) + check_readme_coverage()
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
