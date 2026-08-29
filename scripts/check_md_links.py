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

`--json` replaces the human report with one machine-readable object on stdout
(diagnostics, if any, stay on stderr; the exit code is identical in both modes):

    {
      "passed": true,
      "counts": {
        "md_files_scanned": 97,
        "links_resolved": 210,
        "resources_checked": 58,
        "vendored_files_skipped": 12
      },
      "broken_links": [
        {
          "file": "a/b.md",       # containing file, relative to the repo root
          "line": 12,             # 1-based line the link sits on
          "target": "../x.md",    # link target exactly as written
          "resolved": "a/x.md"    # path the target resolved to (does not exist)
        }
      ],
      "unlinked_resources": [
        {
          "kind": "skill",
          "name": "autofix",
          "path": "src/claude_all/skills/generic/autofix/SKILL.md"
        }
      ]
    }

The counts let a caller detect a vacuous pass — a run that scanned zero files
and exited 0 because a glob stopped matching after a rename.
"""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# [label](target) — skip images, absolute URLs, anchors and mailto. A leading `/` is
# a site-absolute URL (the SEO skill's llms.txt examples), never a repo path.
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "#", "tel:", "/")
FENCE = re.compile(r"^\s*(```|~~~)")
# Inline code spans are not links: `def first[T](...)` reads as [T](...).
CODE_SPAN = re.compile(r"`[^`]*`")


@dataclass
class BrokenLink:
    """One relative link whose target does not exist."""

    file: str  # markdown file containing the link, relative to the repo root
    line: int  # 1-based line the link sits on (the human report points at it)
    target: str  # link target exactly as written, including any #anchor
    resolved: str  # path the target resolved to — root-relative when in-repo


@dataclass
class UnlinkedResource:
    """One discovered resource the README never links to."""

    kind: str  # resource kind as discover() reports it ("skill", "agent", ...)
    name: str
    path: str  # the resource's source file, relative to the repo root


@dataclass
class LinkCheckResult:
    """Findings plus the counts for the relative-link check."""

    broken: list[BrokenLink] = field(default_factory=list)
    md_files_scanned: int = 0
    links_resolved: int = 0
    vendored_files_skipped: int = 0


@dataclass
class CoverageResult:
    """Findings plus the count for the README-coverage check."""

    unlinked: list[UnlinkedResource] = field(default_factory=list)
    resources_checked: int = 0


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


def display_path(path: Path) -> str:
    """Root-relative when the path sits inside the repo, so the JSON report
    stays portable; a link that resolves outside the tree keeps its full path."""
    if path.is_relative_to(ROOT):
        return path.relative_to(ROOT).as_posix()
    return str(path)


def check_links(registry: list[dict]) -> LinkCheckResult:
    result = LinkCheckResult()
    for md in tracked_markdown():
        if is_vendored(md, registry):
            result.vendored_files_skipped += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            continue
        result.md_files_scanned += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                result.links_resolved += 1
                resolved = (md.parent / bare).resolve()
                if not resolved.exists():
                    result.broken.append(
                        BrokenLink(
                            file=md.relative_to(ROOT).as_posix(),
                            line=line_no,
                            target=target,
                            resolved=display_path(resolved),
                        )
                    )
    return result


def check_readme_coverage() -> CoverageResult:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    resources = discover([])
    return CoverageResult(
        unlinked=[
            UnlinkedResource(
                kind=item.kind,
                name=item.name,
                path=item.src.relative_to(ROOT).as_posix(),
            )
            for item in resources
            if f"]({item.src.relative_to(ROOT).as_posix()})" not in readme
        ],
        resources_checked=len(resources),
    )


def human_findings(links: LinkCheckResult, coverage: CoverageResult) -> list[str]:
    """The exact prose lines the gate has always printed — default mode."""
    return [f"{b.file}:{b.line}: broken-link -> {b.target}" for b in links.broken] + [
        f"README.md: undocumented -> {u.kind}/{u.name} (add a row linking {u.path})"
        for u in coverage.unlinked
    ]


def json_report(links: LinkCheckResult, coverage: CoverageResult) -> dict:
    """The --json payload; the shape is documented in the module docstring."""
    return {
        "passed": not links.broken and not coverage.unlinked,
        "counts": {
            "md_files_scanned": links.md_files_scanned,
            "links_resolved": links.links_resolved,
            "resources_checked": coverage.resources_checked,
            "vendored_files_skipped": links.vendored_files_skipped,
        },
        "broken_links": [asdict(b) for b in links.broken],
        "unlinked_resources": [asdict(u) for u in coverage.unlinked],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Relative markdown links resolve + every resource is README-linked."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a single machine-readable JSON object on stdout "
        "(shape documented in the module docstring)",
    )
    args = parser.parse_args(argv)
    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    links = check_links(registry)
    coverage = check_readme_coverage()
    findings = len(links.broken) + len(coverage.unlinked)
    if args.json:
        print(json.dumps(json_report(links, coverage), indent=2))
    else:
        for finding in human_findings(links, coverage):
            print(finding)
    if findings:
        print(f"\n{findings} finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
