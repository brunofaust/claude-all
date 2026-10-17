"""Tests for the markdown link + README-coverage gate.

The gate exists because four cross-skill links shipped broken — one in an
already-merged PR. So the tests that matter are the ones proving it BITES: a
check that can only ever report "clean" is the vacuous pass this repo keeps
hunting. Every positive case is paired with the no-false-positive case that
made the first version of this checker report 18 findings, all of them wrong.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_md_links import (
    CODE_SPAN,
    LINK,
    check_links,
    is_vendored,
    strip_code_blocks,
)
from vendor_sync import clone_upstream

ROOT = Path(__file__).resolve().parent.parent


def test_vendor_clone_supports_pinned_commit_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = "4ec6f84b61cd3c931046c3e6e398f3ae7de372f7"
    destination = tmp_path / "upstream"
    calls: list[tuple[list[str], Path | None]] = []

    def record_git(args: list[str], cwd: Path | None = None) -> str:
        calls.append((args, cwd))
        return commit if args == ["rev-parse", "HEAD"] else ""

    monkeypatch.setattr("vendor_sync.run_git", record_git)

    assert clone_upstream("https://example.com/myorg/myapp", commit, destination) == commit
    assert calls == [
        (
            [
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                "https://example.com/myorg/myapp",
                str(destination),
            ],
            None,
        ),
        (["fetch", "--depth", "1", "origin", commit], destination),
        (["checkout", "--detach", "FETCH_HEAD"], destination),
        (["rev-parse", "HEAD"], destination),
    ]


def targets(line: str) -> list[str]:
    """Link targets a line actually offers, after inline code is discounted."""
    return LINK.findall(CODE_SPAN.sub("", line))


class TestLinkExtraction:
    def test_plain_link_is_found(self) -> None:
        assert targets("see [the audit](references/audit.md) first") == ["references/audit.md"]

    def test_code_labelled_link_keeps_its_target(self) -> None:
        # The README's generated rows look like [`name`](path) — stripping the
        # code span must not take the link with it.
        assert targets("| [`code-quality`](src/a/b.md) | x |") == ["src/a/b.md"]

    def test_bold_labelled_link_keeps_its_target(self) -> None:
        assert targets("| [**frontend**](src/a/b.md) |") == ["src/a/b.md"]

    def test_inline_code_generic_is_not_a_link(self) -> None:
        # `def first[T](...)` reads as [T](...) — 3 of the original false positives.
        assert targets("| PEP 695 | `def first[T](...)` |") == []

    def test_image_is_not_a_link(self) -> None:
        assert targets("![shield](https://img.example.com/b.svg)") == []


class TestStripCodeBlocks:
    def test_fenced_content_is_dropped(self) -> None:
        text = "intro\n```python\n[a](nope.md)\n```\n[b](yes.md)\n"
        kept = [line for _, line in strip_code_blocks(text)]
        assert "[a](nope.md)" not in kept
        assert "[b](yes.md)" in kept

    def test_line_numbers_survive_the_fence(self) -> None:
        # A finding is useless if it points at the wrong line.
        text = "one\n```\nfenced\n```\n[b](yes.md)\n"
        assert (5, "[b](yes.md)") in strip_code_blocks(text)

    def test_tilde_fence_is_honoured(self) -> None:
        text = "~~~\n[a](nope.md)\n~~~\n"
        assert [line for _, line in strip_code_blocks(text)] == []


class TestIsVendored:
    def test_dir_mode_exempts_the_whole_tree(self) -> None:
        registry = [{"path": "src/x/skill", "vendor_mode": "dir"}]
        root = Path(is_vendored.__globals__["ROOT"])
        assert is_vendored(root / "src/x/skill/AGENTS.md", registry)

    def test_local_only_file_stays_checked(self) -> None:
        # ATTRIBUTION.md sits inside a vendored dir but is OURS — a broken link
        # in it is our bug, so the exemption must not swallow it.
        registry = [
            {
                "path": "src/x/skill",
                "vendor_mode": "dir",
                "local_only": ["ATTRIBUTION.md"],
            }
        ]
        root = Path(is_vendored.__globals__["ROOT"])
        assert not is_vendored(root / "src/x/skill/ATTRIBUTION.md", registry)

    def test_files_mode_exempts_only_listed_files(self) -> None:
        registry = [{"path": "src/x/skill", "files": ["SKILL.md"]}]
        root = Path(is_vendored.__globals__["ROOT"])
        assert is_vendored(root / "src/x/skill/SKILL.md", registry)
        assert not is_vendored(root / "src/x/skill/OTHER.md", registry)

    def test_unrelated_path_is_never_exempt(self) -> None:
        registry = [{"path": "src/x/skill", "vendor_mode": "dir"}]
        root = Path(is_vendored.__globals__["ROOT"])
        assert not is_vendored(root / "README.md", registry)


class TestCheckLinks:
    def test_tracked_file_missing_from_disk_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # tracked-but-deleted file must be skipped, not crash read_text()
        missing = tmp_path / "GONE.md"
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [missing])
        findings, broken_links, counts = check_links(registry=[])
        assert findings == []
        assert broken_links == []
        assert counts["markdown_files_scanned"] == 0


def test_main_json_clean_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import check_md_links

    monkeypatch.setattr(
        check_md_links,
        "check_links",
        lambda registry: (
            [],
            [],
            {
                "markdown_files_scanned": 2,
                "links_resolved": 3,
                "vendored_files_skipped": 1,
            },
        ),
    )
    monkeypatch.setattr(check_md_links, "check_readme_coverage", lambda: ([], [], 4))
    monkeypatch.setattr(sys, "argv", ["check_md_links.py", "--json"])
    assert check_md_links.main() == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {
        "passed": True,
        "counts": {
            "markdown_files_scanned": 2,
            "links_resolved": 3,
            "vendored_files_skipped": 1,
            "resources_checked": 4,
        },
        "broken_links": [],
        "unlinked_resources": [],
    }


def test_main_json_findings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import check_md_links

    broken = {"file": "docs/a.md", "target": "missing.md", "resolved_path": "docs/missing.md"}
    monkeypatch.setattr(
        check_md_links,
        "check_links",
        lambda registry: (
            ["docs/a.md:1: broken-link -> missing.md"],
            [broken],
            {"markdown_files_scanned": 1, "links_resolved": 0, "vendored_files_skipped": 0},
        ),
    )
    monkeypatch.setattr(
        check_md_links,
        "check_readme_coverage",
        lambda: (
            ["README.md: undocumented -> skill/x (add a row linking src/x/SKILL.md)"],
            ["src/x/SKILL.md"],
            1,
        ),
    )
    monkeypatch.setattr(sys, "argv", ["check_md_links.py", "--json"])
    assert check_md_links.main() == 1
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["passed"] is False
    assert report["broken_links"] == [broken]
    assert report["unlinked_resources"] == ["src/x/SKILL.md"]
    assert report["counts"]["links_resolved"] == 0
    assert output.err == ""


def test_main_default_output_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import check_md_links

    monkeypatch.setattr(
        check_md_links,
        "check_links",
        lambda registry: (
            ["docs/a.md:1: broken-link -> missing.md"],
            [],
            {"markdown_files_scanned": 1, "links_resolved": 0, "vendored_files_skipped": 0},
        ),
    )
    monkeypatch.setattr(check_md_links, "check_readme_coverage", lambda: ([], [], 1))
    monkeypatch.setattr(sys, "argv", ["check_md_links.py"])
    assert check_md_links.main() == 1
    output = capsys.readouterr()
    assert output.out == "docs/a.md:1: broken-link -> missing.md\n"
    assert output.err == "\n1 finding(s).\n"


def test_json_unlinked_resource_and_exit_code_parity(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import check_md_links

    monkeypatch.setattr(
        check_md_links,
        "check_links",
        lambda registry: (
            [],
            [],
            {
                "markdown_files_scanned": 1,
                "links_resolved": 2,
                "vendored_files_skipped": 0,
            },
        ),
    )
    monkeypatch.setattr(
        check_md_links,
        "check_readme_coverage",
        lambda: (["README.md: undocumented -> skill/x"], ["src/x/SKILL.md"], 1),
    )

    monkeypatch.setattr(sys, "argv", ["check_md_links.py", "--json"])
    json_status = check_md_links.main()
    json_output = capsys.readouterr()
    report = json.loads(json_output.out)
    assert report["passed"] is False
    assert report["unlinked_resources"] == ["src/x/SKILL.md"]
    assert json_status == 1

    monkeypatch.setattr(sys, "argv", ["check_md_links.py"])
    human_status = check_md_links.main()
    human_output = capsys.readouterr()
    assert human_status == json_status
    assert human_output.out == "README.md: undocumented -> skill/x\n"


def test_json_report_shape_is_documented() -> None:
    """The machine output schema remains described alongside the gate."""
    from check_md_links import __doc__

    assert "markdown_files_scanned" in __doc__
    assert "broken_links" in __doc__


def test_non_vendored_routes_use_discoverable_skill_names() -> None:
    """Local routing prose names active Claude skills, not retired aliases."""
    registry = json.loads((ROOT / "vendored.json").read_text(encoding="utf-8"))["vendored"]
    retired_names = {"react-correctness", "react-testing", "web-security"}
    canonical_aliases: dict[str, str] = {}
    for entry in registry:
        if entry.get("kind") != "skill" or entry.get("vendor_mode") != "dir":
            continue
        skill_path = ROOT / entry["path"] / "SKILL.md"
        frontmatter_name = next(
            line.removeprefix("name:").strip()
            for line in skill_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("name:")
        )
        directory_name = Path(entry["path"]).name
        if directory_name != frontmatter_name:
            canonical_aliases[directory_name] = frontmatter_name

    stale_names = retired_names | canonical_aliases.keys()
    findings: list[str] = []
    for path in sorted((ROOT / "src" / "claude_all").rglob("*.md")):
        if is_vendored(path, registry):
            continue
        text = path.read_text(encoding="utf-8")
        for stale_name in sorted(stale_names):
            if f"`{stale_name}`" in text:
                findings.append(f"{path.relative_to(ROOT)} routes to `{stale_name}`")

    assert findings == []


def test_readme_uses_vendored_skill_frontmatter_names() -> None:
    """README labels match the Claude frontmatter names users can invoke."""
    registry = json.loads((ROOT / "vendored.json").read_text(encoding="utf-8"))["vendored"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    findings: list[str] = []
    for entry in registry:
        if entry.get("kind") != "skill" or entry.get("vendor_mode") != "dir":
            continue
        skill_path = ROOT / entry["path"] / "SKILL.md"
        frontmatter_name = next(
            line.removeprefix("name:").strip()
            for line in skill_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("name:")
        )
        if f"[{frontmatter_name}]({entry['path']}/SKILL.md)" not in readme:
            findings.append(frontmatter_name)

    assert findings == []


def test_vendored_local_only_entries_exist() -> None:
    """The vendoring registry does not promise sidecars that are absent on disk."""
    registry = json.loads((ROOT / "vendored.json").read_text(encoding="utf-8"))["vendored"]
    missing = [
        f"{entry['id']}:{relative_path}"
        for entry in registry
        for relative_path in entry.get("local_only", [])
        if not (ROOT / entry["path"] / relative_path).exists()
    ]

    assert missing == []


def test_claude_hook_examples_use_timeout_seconds() -> None:
    """Authored Claude settings examples do not encode millisecond-scale values."""
    timeout_field = re.compile(r'"timeout"\s*:\s*(\d+)')
    findings: list[str] = []
    for path in sorted((ROOT / "src" / "claude_all").rglob("*.md")):
        for value in timeout_field.findall(path.read_text(encoding="utf-8")):
            if int(value) > 600:
                findings.append(f"{path.relative_to(ROOT)}: timeout={value}")

    assert findings == []
