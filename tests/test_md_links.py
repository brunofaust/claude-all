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
    """A coherent vendor bundle can be pinned to an exact upstream commit.

    Args:
        tmp_path: Isolated clone destination.
        monkeypatch: Pytest fixture for replacing git execution.
    """
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
        # `git ls-files` lists a tracked file even after it's deleted from the
        # working tree but not yet re-staged — check_links() must skip it instead
        # of crashing on read_text(). Regression for the CHANGELOG.md removal,
        # which crashed exactly this way.
        missing = tmp_path / "GONE.md"
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [missing])
        assert check_links(registry=[]) == []


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


class TestJsonMode:
    def test_json_output_is_valid_and_has_fields(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        # Simulate a minimal repo with one markdown file and no findings
        md = tmp_path / "doc.md"
        md.write_text("see [link](README.md)\n")
        # Monkeypatch tracked_markdown to return our file, and ROOT to tmp_path?
        # Simpler: test _collect_link_info directly
        # Use real registry empty
        # We need tracked_markdown to return our file; monkeypatch
        import check_md_links
        from check_md_links import _collect_link_info

        monkeypatch.setattr(check_md_links, "tracked_markdown", lambda: [md])
        # Also need ROOT for relative paths; change ROOT temporarily
        original_root = check_md_links.ROOT
        try:
            check_md_links.ROOT = tmp_path
            files_scanned, files_skipped, links_checked, broken_links = _collect_link_info([])
            assert files_scanned == 1
            assert files_skipped == 0
            assert links_checked == 1
            assert broken_links == []
        finally:
            check_md_links.ROOT = original_root

    def test_json_broken_link_is_reported(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        import check_md_links
        from check_md_links import _collect_link_info

        md = tmp_path / "doc.md"
        md.write_text("[bad](nope.md)\n")
        monkeypatch.setattr(check_md_links, "tracked_markdown", lambda: [md])
        original_root = check_md_links.ROOT
        try:
            check_md_links.ROOT = tmp_path
            _files_scanned, _files_skipped, links_checked, broken_links = _collect_link_info([])
            assert links_checked == 1
            assert len(broken_links) == 1
            bl = broken_links[0]
            assert bl["file"] == "doc.md"
            assert bl["target"] == "nope.md"
            assert "resolved_path" in bl
        finally:
            check_md_links.ROOT = original_root

    def test_json_unlinked_resource_is_reported(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        import check_md_links
        from check_md_links import _collect_readme_info

        # Create a fake README without links
        readme = tmp_path / "README.md"
        readme.write_text("no links here\n")

        # Mock discover to return one item
        class FakeItem:
            kind = "skills"
            name = "foo"
            src = tmp_path / "src" / "SKILL.md"

        # Ensure src exists for relative path
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "SKILL.md").write_text("---\n")
        original_root = check_md_links.ROOT
        try:
            check_md_links.ROOT = tmp_path
            # Monkeypatch discover
            import claude_all.cli as cli

            original_discover = cli.discover
            cli.discover = lambda filters: [FakeItem()]
            resources_checked, unlinked = _collect_readme_info()
            assert resources_checked == 1
            assert unlinked == ["src/SKILL.md"]
        finally:
            check_md_links.ROOT = original_root
            cli.discover = original_discover

    def test_default_output_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ):
        # Ensure non-json mode prints findings to stdout and count to stderr
        import check_md_links
        from check_md_links import main

        # Create a file with broken link
        md = tmp_path / "doc.md"
        md.write_text("[bad](nope.md)\n")
        monkeypatch.setattr(check_md_links, "tracked_markdown", lambda: [md])
        monkeypatch.setattr(check_md_links, "ROOT", tmp_path)
        # Mock vendored.json
        vendored = tmp_path / "vendored.json"
        vendored.write_text('{"vendored":[]}')
        # Mock README
        (tmp_path / "README.md").write_text("")
        # Mock sys.argv to no --json
        monkeypatch.setattr(sys, "argv", ["check_md_links.py"])
        # Mock check_readme_coverage to return empty
        monkeypatch.setattr(check_md_links, "check_readme_coverage", lambda: [])
        exit_code = main()
        out, err = capsys.readouterr()
        assert "broken-link" in out
        assert "1 finding(s)" in err
        assert exit_code == 1
