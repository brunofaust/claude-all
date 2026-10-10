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
        broken_links, _, _, _, _, _ = check_links(registry=[])
        assert broken_links == []


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


class TestJsonOutput:
    def run_main(self, argv):
        """Helper to run main with given argv and return (exit_code, stdout, stderr)."""
        import io
        import sys
        from unittest.mock import patch

        old_stderr = sys.stderr
        old_stdout = sys.stdout
        sys.stderr = io.StringIO()
        sys.stdout = io.StringIO()
        try:
            with patch.object(sys, "argv", argv):
                try:
                    check_md_links.main()
                except SystemExit as e:
                    exit_code = e.code
                else:
                    exit_code = 0
            stdout = sys.stdout.getvalue()
            stderr = sys.stderr.getvalue()
            return exit_code, stdout, stderr
        finally:
            sys.stderr = old_stderr
            sys.stdout = old_stdout

    @patch("check_md_links.check_links")
    @patch("check_md_links.ROOT", Path("/dummy"))
    def test_json_clean_tree(self, mock_check_links):
        mock_check_links.return_value = (
            [],  # broken_links
            [],  # unlinked_resources
            5,  # scanned_files
            10,  # resolved_links
            3,  # resources_checks
            2,  # skipped_vendored
        )
        exit_code, stdout, stderr = self.run_main(["check_md_links.py", "--json"])
        assert exit_code == 0
        data = json.loads(stdout)
        assert data["pass"] is True
        assert data["counts"] == {
            "markdown_files_scanned": 5,
            "links_resolved": 10,
            "resources_checked": 3,
            "files_skipped_as_vendored": 2,
        }
        assert data["broken_links"] == []
        assert data["unlinked_resources"] == []
        assert stderr == ""

    @patch("check_md_links.check_links")
    @patch("check_md_links.ROOT", Path("/dummy"))
    def test_json_with_broken_link(self, mock_check_links):
        # We'll create a broken link entry
        broken_file = Path("/dummy") / "doc.md"
        mock_check_links.return_value = (
            [(broken_file, 42, "target.md", Path("/dummy") / "target.md")],  # broken_links
            [],  # unlinked_resources
            1,  # scanned_files
            0,  # resolved_links
            0,  # resources_checks
            0,  # skipped_vendored
        )
        exit_code, stdout, stderr = self.run_main(["check_md_links.py", "--json"])
        assert exit_code == 1
        data = json.loads(stdout)
        assert data["pass"] is False
        assert data["counts"] == {
            "markdown_files_scanned": 1,
            "links_resolved": 0,
            "resources_checked": 0,
            "files_skipped_as_vendored": 0,
        }
        assert len(data["broken_links"]) == 1
        bl = data["broken_links"][0]
        assert bl["file"] == "doc.md"
        assert bl["line"] == 42
        assert bl["target"] == "target.md"
        assert (
            bl["resolved"] == "target.md"
        )  # because ROOT is /dummy, and resolved is /dummy/target.md -> relative is target.md
        assert data["unlinked_resources"] == []
        assert stderr == ""

    @patch("check_md_links.check_links")
    @patch("check_md_links.ROOT", Path("/dummy"))
    def test_json_with_unlinked_resource(self, mock_check_links):
        # We'll create an unlinked resource entry
        # The resource path is relative to ROOT, kind and name
        mock_check_links.return_value = (
            [],  # broken_links
            [(Path("/dummy") / "src/skill/SKILL.md", "skill", "my-skill")],  # unlinked_resources
            1,  # scanned_files
            0,  # resolved_links
            1,  # resources_checks
            0,  # skipped_vendored
        )
        exit_code, stdout, stderr = self.run_main(["check_md_links.py", "--json"])
        assert exit_code == 1
        data = json.loads(stdout)
        assert data["pass"] is False
        assert data["counts"] == {
            "markdown_files_scanned": 1,
            "links_resolved": 0,
            "resources_checked": 1,
            "files_skipped_as_vendored": 0,
        }
        assert data["broken_links"] == []
        assert len(data["unlinked_resources"]) == 1
        ur = data["unlinked_resources"][0]
        assert ur["path"] == "src/skill/SKILL.md"
        assert ur["kind"] == "skill"
        assert ur["name"] == "my-skill"
        assert stderr == ""

    @patch("check_md_links.check_links")
    @patch("check_md_links.ROOT", Path("/dummy"))
    def test_default_output_unaffected(self, mock_check_links):
        # Test that without --json, the output is as expected (human-readable)
        mock_check_links.return_value = (
            [],  # broken_links
            [],  # unlinked_resources
            5,  # scanned_files
            10,  # resolved_links
            3,  # resources_checks
            2,  # skipped_vendored
        )
        exit_code, stdout, stderr = self.run_main(["check_md_links.py"])
        assert exit_code == 0
        assert stdout == ""
        # Expect a message to stderr about the counts
        expected_stderr = "Scanned 5 markdown files, 10 links resolved, 3 resources checked, 2 files skipped as vendored.\n"
        assert stderr == expected_stderr

        # Now with a broken link and unlinked resource to ensure error output
        mock_check_links.return_value = (
            [(Path("/dummy") / "doc.md", 1, "target.md", Path("/dummy") / "target.md")],
            [(Path("/dummy") / "src/skill/SKILL.md", "skill", "my-skill")],
            1,
            0,
            1,
            0,
        )
        exit_code, stdout, stderr = self.run_main(["check_md_links.py"])
        assert exit_code == 1
        assert stdout == ""
        # Check stderr contains the expected lines
        assert "Broken links:" in stderr
        assert "  doc.md:1: target.md -> target.md" in stderr
        assert "Unlinked resources:" in stderr
        assert "  src/skill/SKILL.md (skill: my-skill)" in stderr
        assert "Found 1 broken link(s) and 1 unlinked resource(s)" in stderr
