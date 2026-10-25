#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

--json: emit a single machine-readable object to stdout instead of the human-formatted report.
Human output stays the default and stays byte-identical - this is additive.
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gate: relative markdown links resolve and every resource is linked from the README."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit JSON to stdout instead of human report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry = json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])
    findings = check_links(registry) + check_readme_coverage()
    unlinked = check_readme_coverage()

    if args.json:
        broken_links = []
        for finding in check_links(registry):
            # Format: "{rel}:{line_no}: broken-link -> {target}"
            # Parse to extract file and target
            parts = finding.split(": ", 2)
            if len(parts) >= 3:
                rel_link = parts[0]
                # line_no = parts[1]  # unused - skip line number
                target_part = parts[2]  # "broken-link -> {target}"
                # Extract the actual target after "broken-link -> "
                if "broken-link -> " in target_part:
                    target = target_part.split("broken-link -> ", 1)[1]
                    # The resolved path that did not exist is the target itself
                    # since it was determined that (md.parent / bare).resolve().exists() is False
                    broken_links.append(
                        {
                            "containing_file": rel_link.split(":")[0] if ":" in rel_link else "",
                            "raw_link_target": target,
                            "resolved_path_not_existing": target,
                        }
                    )
            else:
                broken_links.append(
                    {
                        "containing_file": "",
                        "raw_link_target": finding,
                        "resolved_path_not_existing": finding,
                    }
                )

        unlinked_resources = [
            {"path": u.replace("README.md: undocumented -> ", "")} for u in unlinked
        ]

        result = {
            "pass": len(findings) == 0 and len(unlinked) == 0,
            "markdown_files_scanned": len(
                [m for m in tracked_markdown() if not is_vendored(m, registry)]
            ),
            "links_resolved": len(check_links(registry)),
            "resources_checked": len(unlinked) + len(check_links(registry)),
            "files_skipped_as_vendored": len(
                [m for m in tracked_markdown() if is_vendored(m, registry)]
            ),
            "broken_links": broken_links,
            "unlinked_resources": unlinked_resources,
        }
        print(json.dumps(result, indent=2))
        # Exit code is identical: 0 if no findings, 1 if findings exist
        if findings or unlinked:
            return 1
        return 0
    else:
        for finding in findings:
            print(finding)
        if findings:
            print(f"\n{len(findings)} finding(s).", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
