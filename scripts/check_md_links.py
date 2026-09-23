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

JSON output mode:
   With `--json`, the script outputs a single JSON object to stdout and nothing
   else. The JSON has the following shape:

   {
     "passed": boolean,          # True if no findings, False otherwise
     "counts": {
       "markdown_files_scanned": int,   # Number of markdown files processed (non-vendored and existing)
       "links_resolved": int,           # Number of link targets examined (after filtering out SKIP_PREFIX, pure anchors, and code spans)
       "resources_checked": int,        # Number of resources discovered by `discover` that were checked for README linkage
       "files_skipped_vendored": int    # Number of markdown files skipped because they are vendored
     },
     "broken_links": [                 # Each broken link
       {
         "file": string,               # Path to the markdown file containing the broken link (relative to repo root)
         "target": string,             # The raw link target as found in the markdown
         "resolved": string            # The resolved path that did not exist (relative to the markdown file's directory)
       }
     ],
     "unlinked_resources": [           # Each unlinked resource
       string                          # Path to the resource's source file (relative to repo root)
     ]
   }

   Diagnostics (e.g., count of findings) are printed to stderr in both modes.
   Exit code is 0 if passed, 1 otherwise, regardless of output mode.
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


def check_links(registry: list[dict]) -> tuple[list[str], int, int, int]:
    """Check markdown files for broken relative links.

    Returns a tuple of (findings, files_scanned, links_resolved, files_skipped_vendored)
    where:
      findings: list of error messages (human-readable)
      files_scanned: number of markdown files processed (non-vendored and existing)
      links_resolved: number of link targets examined (after filtering out SKIP_PREFIX, pure anchors, and code spans)
      files_skipped_vendored: number of markdown files skipped because they are vendored
    """
    findings = []
    files_scanned = 0
    links_resolved = 0
    files_skipped_vendored = 0
    for md in tracked_markdown():
        if is_vendored(md, registry):
            files_skipped_vendored += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        files_scanned += 1
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
    return findings, files_scanned, links_resolved, files_skipped_vendored


def check_readme_coverage() -> tuple[list[str], int]:
    """Check that every resource discovered is linked from the README.

    Returns a tuple of (findings, resources_checked) where:
      findings: list of error messages (human-readable)
      resources_checked: number of resources discovered by `discover` that were checked for README linkage
    """
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    items = discover([])
    resources_checked = len(items)
    findings = [
        f"README.md: undocumented -> {item.kind}/{item.name} "
        f"(add a row linking {item.src.relative_to(ROOT).as_posix()})"
        for item in items
        if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme
    ]
    return findings, resources_checked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON instead of human-readable report",
    )
    args = parser.parse_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    # Run the checks
    link_findings, files_scanned, links_resolved, files_skipped_vendored = check_links(registry)
    coverage_findings, resources_checked = check_readme_coverage()
    findings = link_findings + coverage_findings

    if args.json:
        # Build JSON output
        broken_links = []
        for finding in link_findings:
            # Parse the human-readable finding to extract file, line_no, target
            # Format: "{relative_file}:{line_no}: broken-link -> {target}"
            # We know the format because we generated it.
            parts = finding.split(": ", 2)
            if len(parts) != 3 or not parts[0].endswith(": broken-link ->"):
                # Fallback: should not happen
                continue
            file_line = parts[0]
            target = parts[2]
            file_part, line_no = file_line.rsplit(":", 1)
            # file_part is the relative path of the markdown file
            # We don't need line_no in the JSON per ticket, but we can include if we want? Ticket didn't ask for line number.
            # We'll omit line number as not explicitly required.
            resolved_path = str((Path(file_part) / Path(target.split("#")[0])).resolve())
            # But we want the resolved path that did not exist, relative to the markdown file's directory?
            # Actually, the resolved path we checked is (md.parent / bare). We want to show that path.
            # However, the ticket says: "the resolved path that did not exist"
            # We'll compute it as the absolute path? But the ticket example in the description doesn't specify.
            # Let's output the resolved path as a string that we checked (which is absolute?).
            # But we want it to be relative to something? The ticket doesn't specify.
            # Looking at the acceptance criteria: they want enough to act without re-parsing prose.
            # We'll output the resolved path as an absolute path? But that might be too specific.
            # Alternatively, we can output the resolved path relative to the repository root?
            # Let's look at the existing human output: it shows the relative file and the target.
            # The resolved path is not shown. We have to compute it.
            # We'll output the resolved path as a string that is the absolute path?
            # But note: the ticket says: "the resolved path that did not exist"
            # We'll output the absolute path for clarity? However, the repository root might be better.
            # We'll output the resolved path relative to the repository root?
            # Let's compute: the resolved path we checked is (md.parent / bare). We can make it relative to ROOT.
            md_path = Path(file_part)
            bare = target.split("#")[0]
            resolved_abs = (md_path.parent / bare).resolve()
            try:
                resolved_rel_to_root = resolved_abs.relative_to(ROOT)
            except ValueError:
                # If it's outside the repo, we output the absolute string?
                resolved_rel_to_root = resolved_abs
            broken_links.append(
                {
                    "file": str(md_path.relative_to(ROOT)),
                    "target": target,
                    "resolved": str(resolved_rel_to_root),
                }
            )

        unlinked_resources = []
        for finding in coverage_findings:
            # Format: "README.md: undocumented -> {kind}/{name} (add a row linking {path})"
            # We want to extract the path from the parentheses.
            # Example: "README.md: undocumented -> skill/code-quality (add a row linking src/claude_all/agents/generic/code-quality/agent.md)"
            # We can split by '(' and then take the part inside until the closing ')'
            if " (add a row linking " in finding:
                path_part = finding.split(" (add a row linking ")[1]
                path_part = path_part.rstrip(")")
                unlinked_resources.append(path_part)
            else:
                # Fallback: should not happen
                unlinked_resources.append(finding)

        output = {
            "passed": len(findings) == 0,
            "counts": {
                "markdown_files_scanned": files_scanned,
                "links_resolved": links_resolved,
                "resources_checked": resources_checked,
                "files_skipped_vendored": files_skipped_vendored,
            },
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }
        print(json.dumps(output))
        # Diagnostics to stderr if there are findings
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
        return 0 if len(findings) == 0 else 1
    else:
        # Original behavior
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
