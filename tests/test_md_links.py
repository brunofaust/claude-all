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
    main,
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

    assert findings == []


class TestJsonOutput:
    """Test the --json output mode."""

    def test_json_clean_tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--json on a clean tree should output a JSON object with passed=True and zero counts."""
        # Set up a temporary git repository with no markdown links issues and all resources linked.
        # We'll monkeypatch the ROOT to point to our temporary directory.
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        # Initialize a git repository.
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("[core]\n")
        # Create a vendored.json with an empty vendored list.
        vendored_json = tmp_path / "vendored.json"
        vendored_json.write_text('{"vendored": []}')
        # Create a README.md that links to a markdown file.
        readme = tmp_path / "README.md"
        readme.write_text("# README\n\n[test](test.md)\n")
        # Create a markdown file with no broken links.
        markdown = tmp_path / "test.md"
        markdown.write_text("# Test\n\nThis is a test.[^1]\n\n[^1]: A footnote.\n")

        # Create a mock resource that is linked in the README.
        # We'll monkeypatch the discover function to return a resource that is linked.
        class MockItem:
            def __init__(self, kind: str, name: str, src: Path) -> None:
                self.kind = kind
                self.name = name
                self.src = src

        def mock_discover() -> list[MockItem]:
            return [MockItem("skill", "test", tmp_path / "test" / "SKILL.md")]

        monkeypatch.setattr("claude_all.cli.discover", mock_discover)
        # Create the resource's source file (so it exists).
        (tmp_path / "test" / "SKILL.md").parent.mkdir()
        (tmp_path / "test" / "SKILL.md").write_text("# Test Skill\n")

        # Capture stdout and stderr.
        import sys
        from io import StringIO

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        old_argv = sys.argv
        try:
            sys.argv = ["check_md_links.py", "--json"]
            # Run main with --json.
            exit_code = main()
            # Get the output.
            stdout = sys.stdout.getvalue()
            stderr = sys.stderr.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            sys.argv = old_argv

        # Parse the JSON output.
        data = json.loads(stdout)
        # Check that the check passed.
        assert data["passed"] is True
        # Check that the counts are as expected.
        assert data["markdown_files_scanned"] == 1  # test.md
        assert (
            data["links_resolved"] == 0
        )  # no links in test.md (footnote not a link; README link not in scanned file)
        assert data["resources_checked"] == 1
        assert data["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert data["unlinked_resources"] == []  # resource linked in README
        # Check that there is no output to stderr (no diagnostics).
        assert stderr == ""
        # Check exit code.
        assert exit_code == 0

    def test_json_broken_link(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--json with a broken link should output the broken link details."""
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("[core]\n")
        vendored_json = tmp_path / "vendored.json"
        vendored_json.write_text('{"vendored": []}')
        readme = tmp_path / "README.md"
        readme.write_text("# README\n\n[test](test.md)\n")
        markdown = tmp_path / "test.md"
        # Create a broken link in the markdown file.
        markdown.write_text("# Test\n\n[link](nonexistent.md)\n")

        # No resources to keep it simple.
        def mock_discover() -> list:
            return []

        monkeypatch.setattr("claude_all.cli.discover", mock_discover)

        import sys
        from io import StringIO

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        old_argv = sys.argv
        try:
            sys.argv = ["check_md_links.py", "--json"]
            exit_code = main()
            stdout = sys.stdout.getvalue()
            stderr = sys.stderr.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            sys.argv = old_argv

        data = json.loads(stdout)
        assert data["passed"] is False
        assert data["markdown_files_scanned"] == 1
        assert data["links_resolved"] == 1  # one link examined
        assert data["resources_checked"] == 0
        assert data["files_skipped_as_vendored"] == 0
        assert len(data["broken_links"]) == 1
        broken = data["broken_links"][0]
        assert broken["file"] == "test.md"
        assert broken["line"] == 2
        assert broken["target"] == "nonexistent.md"
        # The resolved path should be the absolute path of nonexistent.md relative to test.md.
        expected_resolved = (tmp_path / "nonexistent.md").resolve()
        assert broken["resolved_path"] == str(expected_resolved)
        assert data["unlinked_resources"] == []
        # In JSON mode, we print count to stderr if there are findings.
        # So we expect stderr to have a line about 1 finding.
        assert "1 finding(s)" in stderr
        assert exit_code == 1

    def test_json_unlinked_resource(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--json with an unlinked resource should output the resource details."""
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("[core]\n")
        vendored_json = tmp_path / "vendored.json"
        vendored_json.write_text('{"vendored": []}')
        readme = tmp_path / "README.md"
        readme.write_text("# README\n\nNo links here.\n")
        # Create a markdown file with no links.
        markdown = tmp_path / "test.md"
        markdown.write_text("# Test\n\nNo links.\n")

        # Create a mock resource that is not linked in the README.
        class MockItem:
            def __init__(self, kind: str, name: str, src: Path) -> None:
                self.kind = kind
                self.name = name
                self.src = src

        def mock_discover() -> list[MockItem]:
            return [MockItem("skill", "unlinked", tmp_path / "unlinked" / "SKILL.md")]

        monkeypatch.setattr("claude_all.cli.discover", mock_discover)
        # Create the resource's source file (existence not required for README link check).
        # The check for README linkage only cares about the link in the README.
        (tmp_path / "unlinked" / "SKILL.md").parent.mkdir()
        (tmp_path / "unlinked" / "SKILL.md").write_text("# Unlinked Skill\n")

        import sys
        from io import StringIO

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        old_argv = sys.argv
        try:
            sys.argv = ["check_md_links.py", "--json"]
            exit_code = main()
            stdout = sys.stdout.getvalue()
            stderr = sys.stderr.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            sys.argv = old_argv

        data = json.loads(stdout)
        assert data["passed"] is False
        assert data["markdown_files_scanned"] == 1
        assert data["links_resolved"] == 0
        assert data["resources_checked"] == 1
        assert data["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert len(data["unlinked_resources"]) == 1
        unlinked = data["unlinked_resources"][0]
        assert unlinked["kind"] == "skill"
        assert unlinked["name"] == "unlinked"
        assert unlinked["path"] == "unlinked/SKILL.md"
        assert "1 finding(s)" in stderr
        assert exit_code == 1

    def test_json_output_unaffected_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default (non-JSON) output should be unaffected by the --json flag."""
        # We'll test that without --json, the output is the same as before.
        # We'll use a scenario with one broken link and one unlinked resource.
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("[core]\n")
        vendored_json = tmp_path / "vendored.json"
        vendored_json.write_text('{"vendored": []}')
        readme = tmp_path / "README.md"
        readme.write_text("# README\n\n[test](test.md)\n")
        markdown = tmp_path / "test.md"
        markdown.write_text("# Test\n\n[link](nonexistent.md)\n")

        # Resource that is not linked.
        class MockItem:
            def __init__(self, kind: str, name: str, src: Path) -> None:
                self.kind = kind
                self.name = name
                self.src = src

        def mock_discover() -> list[MockItem]:
            return [MockItem("skill", "unlinked", tmp_path / "unlinked" / "SKILL.md")]

        monkeypatch.setattr("claude_all.cli.discover", mock_discover)
        (tmp_path / "unlinked" / "SKILL.md").parent.mkdir()
        (tmp_path / "unlinked" / "SKILL.md").write_text("# Unlinked Skill\n")

        import sys
        from io import StringIO

        # Test without --json.
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        old_argv = sys.argv
        try:
            sys.argv = ["check_md_links.py"]
            exit_code = main()
            stdout_no_json = sys.stdout.getvalue()
            stderr_no_json = sys.stderr.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            sys.argv = old_argv

        # Test with --json.
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        old_argv = sys.argv
        try:
            sys.argv = ["check_md_links.py", "--json"]
            exit_code = main()
            stdout_json = sys.stdout.getvalue()
            stderr_json = sys.stderr.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            sys.argv = old_argv

        # Without --json, we expect the human-readable output.
        # The findings should be:
        #   test.md:2: broken-link -> nonexistent.md
        #   README.md: undocumented -> skill/unlinked (add a row linking unlinked/SKILL.md)
        # In any order? The order is: check_links first, then check_readme_coverage.
        expected_lines = [
            "test.md:2: broken-link -> nonexistent.md",
            "README.md: undocumented -> skill/unlinked (add a row linking unlinked/SKILL.md)",
        ]
        # The output is each finding on a separate line.
        actual_lines = stdout_no_json.strip().split("\n")
        assert set(actual_lines) == set(expected_lines)
        # The stderr should have the count.
        assert "2 finding(s)" in stderr_no_json
        assert exit_code == 1

        # With --json, we expect the JSON object.
        data = json.loads(stdout_json)
        assert data["passed"] is False
        assert data["markdown_files_scanned"] == 1
        assert data["links_resolved"] == 1
        assert data["resources_checked"] == 1
        assert data["files_skipped_as_vendored"] == 0
        assert len(data["broken_links"]) == 1
        broken = data["broken_links"][0]
        assert broken["file"] == "test.md"
        assert broken["line"] == 2
        assert broken["target"] == "nonexistent.md"
        assert len(data["unlinked_resources"]) == 1
        unlinked = data["unlinked_resources"][0]
        assert unlinked["kind"] == "skill"
        assert unlinked["name"] == "unlinked"
        assert unlinked["path"] == "unlinked/SKILL.md"
        # The stderr should have the count (same as without --json).
        assert "2 finding(s)" in stderr_json
        assert exit_code == 1

        # Ensure that the JSON output is not the same as the human-readable output.
        assert stdout_json != stdout_no_json
