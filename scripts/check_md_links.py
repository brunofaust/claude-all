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

--json mode
-----------
Added for machine-readable gate results. With ``--json`` the script emits a single
JSON object to stdout and nothing else; diagnostics go to stderr. Human output is
the default and unchanged.

JSON shape::

    {
      "pass": bool,
      "markdown_files_scanned": int,
      "files_skipped_as_vendored": int,
      "links_resolved": int,
      "resources_checked": int,
      "broken_links": [
        {
          "file": "path/relative/to/root.md",
          "target": "raw link target",
          "resolved_path": "path/relative/to/root or absolute"
        }
      ],
      "unlinked_resources": [
        {
          "path": "path/relative/to/root"
        }
      ]
    }

* ``pass`` is True when no findings exist.
* ``markdown_files_scanned`` is the total number of ``*.md`` files returned by
  ``git ls-files``.
* ``files_skipped_as_vendored`` is the subset of those files exempted by the
  vendoring registry.
* ``links_resolved`` is the number of link targets examined after stripping code
  spans, fenced blocks, images, absolute URLs and pure anchors in non-vendored,
  existing files.
* ``resources_checked`` is the total number of resources discovered by
  ``claude_all.cli.discover([])``.
* ``broken_links`` lists each unresolved relative link with its containing file,
  raw target and the resolved path that did not exist.
* ``unlinked_resources`` lists the source paths of resources not referenced in
  ``README.md``.
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


def check_links(registry: list[dict]) -> list[str]:
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
    # Parse --json flag without affecting existing behaviour
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--json", action="store_true")
    args, _ = parser.parse_known_args()

    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])

    # --- collect markdown link data ---
    all_md = tracked_markdown()
    markdown_files_scanned = len(all_md)
    files_skipped_as_vendored = 0
    links_resolved = 0
    broken_links = []  # detailed for JSON, also used for human findings

    for md in all_md:
        if is_vendored(md, registry):
            files_skipped_as_vendored += 1
            continue
        if not md.exists():
            continue
        text = md.read_text()
        for line_no, line in strip_code_blocks(text):
            stripped = CODE_SPAN.sub("", line)
            for target in LINK.findall(stripped):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue
                links_resolved += 1
                resolved = (md.parent / bare).resolve()
                if not resolved.exists():
                    file_rel = md.relative_to(ROOT).as_posix()
                    try:
                        resolved_rel = resolved.relative_to(ROOT).as_posix()
                    except ValueError:
                        resolved_rel = str(resolved)
                    broken_links.append(
                        {
                            "file": file_rel,
                            "line_no": line_no,
                            "target": target,
                            "resolved_path": resolved_rel,
                        }
                    )

    # --- README coverage ---
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    items = discover([])
    resources_checked = len(items)
    readme_text = (ROOT / "README.md").read_text()
    unlinked_resources = []
    for item in items:
        src_rel = item.src.relative_to(ROOT).as_posix()
        if f"]({src_rel})" not in readme_text:
            unlinked_resources.append({"path": src_rel, "kind": item.kind, "name": item.name})

    # Build human findings to preserve exact prior output
    findings = []
    for bl in broken_links:
        findings.append(f"{bl['file']}:{bl['line_no']}: broken-link -> {bl['target']}")
    for item in items:
        src_rel = item.src.relative_to(ROOT).as_posix()
        if f"]({src_rel})" not in readme_text:
            findings.append(
                f"README.md: undocumented -> {item.kind}/{item.name} (add a row linking {src_rel})"
            )

    passed = not findings

    if args.json:
        json_out = {
            "pass": passed,
            "markdown_files_scanned": markdown_files_scanned,
            "files_skipped_as_vendored": files_skipped_as_vendored,
            "links_resolved": links_resolved,
            "resources_checked": resources_checked,
            "broken_links": [
                {"file": bl["file"], "target": bl["target"], "resolved_path": bl["resolved_path"]}
                for bl in broken_links
            ],
            "unlinked_resources": [{"path": ur["path"]} for ur in unlinked_resources],
        }
        # JSON only on stdout
        print(json.dumps(json_out))
        return 0 if passed else 1
    else:
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
