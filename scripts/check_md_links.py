#!/usr/bin/env python3
"""Gate: relative markdown links resolve and every resource is linked from the README.

Vendored files are exempt from the link check (kept byte-identical to upstream);
their `local_only` sidecars stay checked. README links are the proxy for "documented".

`--json` emits one machine-readable object on stdout instead of the human report.
The JSON shape, count meanings and path conventions are documented in
docs/check-md-links.md.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1

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


def repo_posix(path: Path) -> str:
    """Lexically normalised, repo-relative POSIX form of `path`."""
    return Path(os.path.relpath(os.path.normpath(path), ROOT)).as_posix()


def check_links(registry: list[dict]) -> dict:
    tracked = tracked_markdown()
    counts = {
        "markdown_tracked": len(tracked),
        "markdown_scanned": 0,
        "markdown_skipped_vendored": 0,
        "markdown_skipped_missing": 0,
        "links_checked": 0,
        "links_resolved": 0,
    }
    broken_links = []
    for md in tracked:
        if is_vendored(md, registry):
            counts["markdown_skipped_vendored"] += 1
            continue
        if not md.exists():
            # `git ls-files` reflects the INDEX: a tracked file deleted from the
            # working tree but not yet re-staged (`git rm`/`git add`) still shows up
            # here. Nothing left to check its links against.
            counts["markdown_skipped_missing"] += 1
            continue
        counts["markdown_scanned"] += 1
        for line_no, line in strip_code_blocks(md.read_text()):
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if target.startswith(SKIP_PREFIX):
                    continue
                bare = target.split("#", 1)[0]
                if not bare:
                    continue  # pure anchor
                counts["links_checked"] += 1
                if (md.parent / bare).resolve().exists():
                    counts["links_resolved"] += 1
                    continue
                broken_links.append(
                    {
                        "file": md.relative_to(ROOT).as_posix(),
                        "line": line_no,
                        "target": target,
                        "resolved": repo_posix(md.parent / bare),
                    }
                )
    return {"counts": counts, "broken_links": broken_links}


def check_readme_coverage() -> dict:
    sys.path.insert(0, str(ROOT / "src"))
    from claude_all.cli import discover

    readme = (ROOT / "README.md").read_text()
    resources_by_kind: dict[str, int] = {}
    unlinked_resources = []
    items = discover([])
    for item in items:
        resources_by_kind[item.kind] = resources_by_kind.get(item.kind, 0) + 1
        path = item.src.relative_to(ROOT).as_posix()
        if f"]({path})" not in readme:
            unlinked_resources.append({"kind": item.kind, "name": item.name, "path": path})
    return {
        "resources_checked": len(items),
        "resources_by_kind": resources_by_kind,
        "unlinked_resources": unlinked_resources,
    }


def build_report(registry: list[dict]) -> dict:
    links = check_links(registry)
    readme = check_readme_coverage()
    counts = dict(links["counts"])
    counts["resources_checked"] = readme["resources_checked"]
    counts["resources_by_kind"] = readme["resources_by_kind"]
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": not links["broken_links"] and not readme["unlinked_resources"],
        "counts": counts,
        "broken_links": links["broken_links"],
        "unlinked_resources": readme["unlinked_resources"],
    }


def human_findings(report: dict) -> list[str]:
    findings = [
        f"{b['file']}:{b['line']}: broken-link -> {b['target']}" for b in report["broken_links"]
    ]
    findings += [
        f"README.md: undocumented -> {r['kind']}/{r['name']} (add a row linking {r['path']})"
        for r in report["unlinked_resources"]
    ]
    return findings


def load_registry() -> list[dict]:
    return json.loads((ROOT / "vendored.json").read_text()).get("vendored", [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a single machine-readable JSON object on stdout",
    )
    args = parser.parse_args(argv)
    registry = load_registry()

    if args.json:
        try:
            report = build_report(registry)
        except subprocess.CalledProcessError as exc:
            error = f"git ls-files failed (exit {exc.returncode}): {exc.stderr or exc}"
            print(
                json.dumps(
                    {"schema_version": SCHEMA_VERSION, "ok": False, "error": error},
                    indent=2,
                )
            )
            print(f"check_md_links: {error}", file=sys.stderr)
            return 1
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    report = build_report(registry)
    findings = human_findings(report)
    for finding in findings:
        print(finding)
    if findings:
        print(f"\n{len(findings)} finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
