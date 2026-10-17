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
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from check_md_links import (
    CODE_SPAN,
    LINK,
    check_links,
    check_readme_coverage,
    is_vendored,
    strip_code_blocks,
)

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
        assert check_links(registry=[]) == (
            [],
            {"markdown_files_scanned": 0, "links_resolved": 0, "files_skipped_vendored": 0},
        )


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
    findings, _ = check_readme_coverage()
    # Convert findings back to the expected format for this test
    finding_names = [f"{finding['kind']}/{finding['name']}" for finding in findings]
    assert finding_names == []


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


class TestJsonOutput(unittest.TestCase):
    def setUp(self):
        self.registry = []

    @patch("check_md_links.tracked_markdown")
    @patch("check_md_links.is_vendored")
    @patch("claude_all.cli.discover")
    def test_json_output_clean_tree(self, mock_discover, mock_is_vendored, mock_tracked_markdown):
        # Mock a clean tree with no findings
        mock_tracked_markdown.return_value = [Path("test.md")]
        mock_is_vendored.return_value = False
        mock_discover.return_value = []

        # Mock file content with no links
        with patch("builtins.open", unittest.mock.mock_open(read_data="")):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.read_text", return_value=""):
                    # Capture stdout
                    import io
                    import sys

                    import check_md_links

                    old_stdout = sys.stdout
                    sys.stdout = io.StringIO()

                    try:
                        # Test JSON output
                        check_md_links.main(["--json"])
                        output = sys.stdout.getvalue()
                        result = json.loads(output)

                        # Verify JSON structure
                        self.assertTrue(result["passed"])
                        self.assertEqual(result["markdown_files_scanned"], 1)
                        self.assertEqual(result["links_resolved"], 0)
                        self.assertEqual(result["resources_checked"], 0)
                        self.assertEqual(result["files_skipped_vendored"], 0)
                        self.assertEqual(result["broken_links"], [])
                        self.assertEqual(result["unlinked_resources"], [])
                    finally:
                        sys.stdout = old_stdout

    @patch("check_md_links.tracked_markdown")
    @patch("check_md_links.is_vendored")
    @patch("claude_all.cli.discover")
    def test_json_output_with_broken_link(
        self, mock_discover, mock_is_vendored, mock_tracked_markdown
    ):
        # Mock a file with a broken link
        mock_tracked_markdown.return_value = [Path("test.md")]
        mock_is_vendored.return_value = False
        mock_discover.return_value = []

        # Mock file content with a broken link
        with patch("builtins.open", unittest.mock.mock_open(read_data="[link](nonexistent.md)")):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.read_text", return_value="[link](nonexistent.md)"):
                    with patch(
                        "pathlib.Path.resolve", return_value=Path("/fake/path/nonexistent.md")
                    ):
                        # Capture stdout
                        import io
                        import sys

                        import check_md_links

                        old_stdout = sys.stdout
                        sys.stdout = io.StringIO()

                        try:
                            # Test JSON output
                            check_md_links.main(["--json"])
                            output = sys.stdout.getvalue()
                            result = json.loads(output)

                            # Verify JSON structure
                            self.assertFalse(result["passed"])
                            self.assertEqual(result["markdown_files_scanned"], 1)
                            self.assertEqual(result["links_resolved"], 1)
                            self.assertEqual(result["resources_checked"], 0)
                            self.assertEqual(result["files_skipped_vendored"], 0)
                            self.assertEqual(len(result["broken_links"]), 1)
                            broken_link = result["broken_links"][0]
                            self.assertEqual(broken_link["file"], "test.md")
                            self.assertEqual(broken_link["line"], 1)
                            self.assertEqual(broken_link["target"], "nonexistent.md")
                            self.assertEqual(result["unlinked_resources"], [])
                        finally:
                            sys.stdout = old_stdout

    @patch("check_md_links.tracked_markdown")
    @patch("check_md_links.is_vendored")
    @patch("claude_all.cli.discover")
    def test_json_output_with_unlinked_resource(
        self, mock_discover, mock_is_vendored, mock_tracked_markdown
    ):
        # Mock a clean link check but with unlinked resource
        mock_tracked_markdown.return_value = [Path("test.md")]
        mock_is_vendored.return_value = False

        # Mock file content with no links
        with patch("builtins.open", unittest.mock.mock_open(read_data="")):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.read_text", return_value=""):
                    # Mock discover to return a resource
                    mock_item = unittest.mock.MagicMock()
                    mock_item.kind = "skill"
                    mock_item.name = "test-skill"
                    mock_item.src = Path("src/test/skill/SKILL.md")
                    mock_discover.return_value = [mock_item]

                    # Capture stdout
                    import io
                    import sys

                    import check_md_links

                    old_stdout = sys.stdout
                    sys.stdout = io.StringIO()

                    try:
                        # Test JSON output
                        check_md_links.main(["--json"])
                        output = sys.stdout.getvalue()
                        result = json.loads(output)

                        # Verify JSON structure
                        self.assertFalse(result["passed"])
                        self.assertEqual(result["markdown_files_scanned"], 1)
                        self.assertEqual(result["links_resolved"], 0)
                        self.assertEqual(result["resources_checked"], 1)
                        self.assertEqual(result["files_skipped_vendored"], 0)
                        self.assertEqual(result["broken_links"], [])
                        self.assertEqual(len(result["unlinked_resources"]), 1)
                        resource = result["unlinked_resources"][0]
                        self.assertEqual(resource["kind"], "skill")
                        self.assertEqual(resource["name"], "test-skill")
                        self.assertEqual(resource["src"], "src/test/skill/SKILL.md")
                    finally:
                        sys.stdout = old_stdout

    @patch("check_md_links.tracked_markdown")
    @patch("check_md_links.is_vendored")
    @patch("claude_all.cli.discover")
    def test_default_output_unchanged(self, mock_discover, mock_is_vendored, mock_tracked_markdown):
        # Test that default (non-JSON) output is unchanged
        mock_tracked_markdown.return_value = [Path("test.md")]
        mock_is_vendored.return_value = False
        mock_discover.return_value = []

        # Mock file content with a broken link
        with patch("builtins.open", unittest.mock.mock_open(read_data="[link](nonexistent.md)")):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.read_text", return_value="[link](nonexistent.md)"):
                    with patch(
                        "pathlib.Path.resolve", return_value=Path("/fake/path/nonexistent.md")
                    ):
                        # Capture stdout
                        import io
                        import sys

                        import check_md_links

                        old_stdout = sys.stdout
                        sys.stdout = io.StringIO()

                        try:
                            # Test default output (no --json flag)
                            check_md_links.main([])
                            output = sys.stdout.getvalue()

                            # Should contain human-readable format
                            self.assertIn("test.md:1: broken-link -> nonexistent.md", output)
                            self.assertIn("\n1 finding(s).", output)
                        finally:
                            sys.stdout = old_stdout
