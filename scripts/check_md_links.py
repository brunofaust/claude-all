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

With the `--json` flag, the script emits a single JSON object to stdout containing:
* `pass`: boolean indicating overall pass/fail
* `counts`: object with:
    - `markdown_files_scanned`: total number of Markdown files found via `git ls-files`
    - `links_resolved`: number of link targets examined (after filtering) in non-vendored files
    - `resources_checked`: number of resources discovered for README coverage check
    - `files_skipped_as_vendored`: number of Markdown files skipped due to vendored exemption
* `broken_links`: array of objects, each with:
    - `file`: path of the Markdown file containing the broken link (relative to repository root)
    - `target`: raw link target as found in the Markdown
    - `resolved_path`: absolute path that was checked for existence and did not exist
* `unlinked_resources`: array of strings, each being the path (relative to repository root)
  of a resource not linked from the README

Without `--json`, the output and exit codes are unchanged from the original behavior.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Module-level variable for discover, initialized lazily
discover = None


def _setup_discover():
    """Initialize the discover function by adjusting sys.path and importing."""
    global discover
    if discover is None:
        sys.path.insert(0, str(ROOT / "src"))
        from claude_all.cli import discover as d

        discover = d


# Initialize discover at module level
_setup_discover()


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


def _check_links_detailed(registry: list[dict]):
    """Check Markdown links in non-vendored files.

    Returns a tuple of:
        - list of human-readable findings strings
        - list of broken link info dicts (for JSON output)
        - count of link targets examined (after filtering)
        - count of files skipped due to vendored exemption
    """
    findings = []
    broken_links_info = []
    links_checked = 0
    files_skipped = 0
    for md in tracked_markdown():
        if is_vendored(md, registry):
            files_skipped += 1
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
                links_checked += 1
                if not (md.parent / bare).resolve().exists():
                    rel = md.relative_to(ROOT)
                    findings.append(f"{rel}:{line_no}: broken-link -> {target}")
                    broken_links_info.append(
                        {
                            "file": rel.as_posix(),
                            "target": target,
                            "resolved_path": (md.parent / bare).resolve().as_posix(),
                        }
                    )
    return findings, broken_links_info, links_checked, files_skipped


def check_links(registry: list[dict]) -> list[str]:
    """Check Markdown links in non-vendored files.

    Returns a list of human-readable findings strings (for backward compatibility).
    """
    findings, _, _, _ = _check_links_detailed(registry)
    return findings


def _check_readme_coverage_detailed():
    """Check README coverage for resources.

    Returns a tuple of:
        - list of human-readable findings strings
        - list of unlinked resource paths (relative to repository root, as strings)
        - count of resources checked
    """
    readme = (ROOT / "README.md").read_text()
    findings = []
    unlinked_resources = []
    resources_checked = 0
    for item in discover([]):
        resources_checked += 1
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme:
            findings.append(
                f"README.md: undocumented -> {item.kind}/{item.name} "
                f"(add a row linking {item.src.relative_to(ROOT).as_posix()})"
            )
            unlinked_resources.append(item.src.relative_to(ROOT).as_posix())
    return findings, unlinked_resources, resources_checked


def check_readme_coverage() -> list[str]:
    """Check README coverage for resources.

    Returns a list of human-readable findings strings (for backward compatibility).
    """
    findings, _, _ = _check_readme_coverage_detailed()
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable output",
    )
    args, _ = parser.parse_known_args()  # Ignore unknown arguments (e.g., from pytest)

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    if args.json:
        findings_strings, broken_links_info, links_checked, files_skipped = _check_links_detailed(
            registry
        )
        coverage_strings, unlinked_resources, resources_checked = _check_readme_coverage_detailed()
        findings = findings_strings + coverage_strings
        markdown_files = tracked_markdown()
        markdown_files_scanned = len(markdown_files)
        pass_fail = len(findings) == 0
        data = {
            "pass": pass_fail,
            "counts": {
                "markdown_files_scanned": markdown_files_scanned,
                "links_resolved": links_checked,
                "resources_checked": resources_checked,
                "files_skipped_as_vendored": files_skipped,
            },
            "broken_links": [
                {
                    "file": info["file"],
                    "target": info["target"],
                    "resolved_path": info["resolved_path"],
                }
                for info in broken_links_info
            ],
            "unlinked_resources": unlinked_resources,
        }
        print(json.dumps(data))
        return 0 if pass_fail else 1
    else:
        findings_strings = check_links(registry)
        coverage_strings = check_readme_coverage()
        findings = findings_strings + coverage_strings
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
