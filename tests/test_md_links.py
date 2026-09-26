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
    format_human_output,
    format_json_output,
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
        broken_links, scanned, checked, skipped = check_links(registry=[])
        assert broken_links == []
        assert scanned == 0
        assert checked == 0
        assert skipped == 0

    def test_vendored_file_is_skipped_and_counted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        vendored_file = tmp_path / "VENDORED.md"
        vendored_file.write_text("[link](target.md)\n")
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [vendored_file])
        registry = [{"path": str(tmp_path), "vendor_mode": "dir"}]
        broken_links, scanned, checked, skipped = check_links(registry=registry)
        assert broken_links == []
        assert scanned == 0
        assert checked == 0
        assert skipped == 1


class TestFormatHumanOutput:
    def test_formats_broken_link(self) -> None:
        broken_links = [
            {
                "file": "docs/foo.md",
                "line": 10,
                "raw_target": "../bar.md",
                "resolved_path": "/abs/path/bar.md",
            }
        ]
        out = format_human_output(broken_links, [])
        assert out == ["docs/foo.md:10: broken-link -> ../bar.md"]

    def test_formats_unlinked_resource(self) -> None:
        out = format_human_output([], ["src/skill/SKILL.md"])
        assert out == [
            "README.md: undocumented -> src/skill/SKILL.md (add a row linking src/skill/SKILL.md)"
        ]

    def test_formats_both(self) -> None:
        broken_links = [
            {
                "file": "docs/foo.md",
                "line": 10,
                "raw_target": "../bar.md",
                "resolved_path": "/abs/path/bar.md",
            }
        ]
        out = format_human_output(broken_links, ["src/skill/SKILL.md"])
        assert out == [
            "docs/foo.md:10: broken-link -> ../bar.md",
            "README.md: undocumented -> src/skill/SKILL.md (add a row linking src/skill/SKILL.md)",
        ]


class TestFormatJsonOutput:
    def test_clean_tree(self) -> None:
        output = format_json_output(
            broken_links=[],
            unlinked_resources=[],
            markdown_files_scanned=5,
            links_checked=10,
            resources_checked=3,
            vendored_files_skipped=2,
        )
        assert output["passed"] is True
        assert output["counts"] == {
            "markdown_files_scanned": 5,
            "links_checked": 10,
            "resources_checked": 3,
            "vendored_files_skipped": 2,
        }
        assert output["broken_links"] == []
        assert output["unlinked_resources"] == []

    def test_with_broken_link(self) -> None:
        broken_links = [
            {
                "file": "docs/foo.md",
                "line": 10,
                "raw_target": "../bar.md",
                "resolved_path": "/abs/path/bar.md",
            }
        ]
        output = format_json_output(
            broken_links=broken_links,
            unlinked_resources=[],
            markdown_files_scanned=5,
            links_checked=10,
            resources_checked=3,
            vendored_files_skipped=2,
        )
        assert output["passed"] is False
        assert output["broken_links"] == broken_links

    def test_with_unlinked_resource(self) -> None:
        output = format_json_output(
            broken_links=[],
            unlinked_resources=["src/skill/SKILL.md"],
            markdown_files_scanned=5,
            links_checked=10,
            resources_checked=3,
            vendored_files_skipped=2,
        )
        assert output["passed"] is False
        assert output["unlinked_resources"] == ["src/skill/SKILL.md"]

    def test_schema_stability(self) -> None:
        """All expected keys are present and have the right types."""
        output = format_json_output(
            broken_links=[
                {"file": "a.md", "line": 1, "raw_target": "b.md", "resolved_path": "/x/b.md"}
            ],
            unlinked_resources=["c.md"],
            markdown_files_scanned=1,
            links_checked=1,
            resources_checked=1,
            vendored_files_skipped=0,
        )
        assert set(output.keys()) == {"passed", "counts", "broken_links", "unlinked_resources"}
        assert isinstance(output["passed"], bool)
        assert set(output["counts"].keys()) == {
            "markdown_files_scanned",
            "links_checked",
            "resources_checked",
            "vendored_files_skipped",
        }
        for v in output["counts"].values():
            assert isinstance(v, int)
        assert isinstance(output["broken_links"], list)
        for bl in output["broken_links"]:
            assert set(bl.keys()) == {"file", "line", "raw_target", "resolved_path"}
            assert isinstance(bl["file"], str)
            assert isinstance(bl["line"], int)
            assert isinstance(bl["raw_target"], str)
            assert isinstance(bl["resolved_path"], str)
        assert isinstance(output["unlinked_resources"], list)
        for ur in output["unlinked_resources"]:
            assert isinstance(ur, str)


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


class TestJsonOutputMode:
    """Integration tests for the --json CLI flag."""

    def test_json_on_clean_tree(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """--json on a clean tree emits valid JSON with passed=true."""
        # Create a temp markdown file with a valid link
        md_file = tmp_path / "test.md"
        target_file = tmp_path / "target.md"
        target_file.write_text("# Target\n")
        md_file.write_text("[link](target.md)\n")

        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)

        # Also mock check_readme_coverage to return clean
        monkeypatch.setattr("check_md_links.check_readme_coverage", lambda: ([], 0))

        # Capture stdout
        import io
        from contextlib import redirect_stderr, redirect_stdout

        import check_md_links

        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            # Simulate --json argument
            import sys

            original_argv = sys.argv
            sys.argv = ["check_md_links.py", "--json"]
            try:
                exit_code = check_md_links.main()
            finally:
                sys.argv = original_argv

        assert exit_code == 0
        stderr_output = stderr_capture.getvalue()
        assert stderr_output == ""  # No diagnostics on stderr for clean run

        stdout_output = stdout_capture.getvalue().strip()
        # Should be valid JSON
        data = json.loads(stdout_output)
        assert data["passed"] is True
        assert data["counts"]["markdown_files_scanned"] == 1
        assert data["counts"]["links_checked"] == 1
        assert data["counts"]["vendored_files_skipped"] == 0
        assert data["broken_links"] == []
        assert data["unlinked_resources"] == []

    def test_json_with_broken_link(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """--json with broken link emits JSON with passed=false and broken_links."""
        md_file = tmp_path / "test.md"
        md_file.write_text("[link](missing.md)\n")

        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        monkeypatch.setattr("check_md_links.check_readme_coverage", lambda: ([], 0))

        import io
        import sys
        from contextlib import redirect_stderr, redirect_stdout

        import check_md_links

        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            original_argv = sys.argv
            sys.argv = ["check_md_links.py", "--json"]
            try:
                exit_code = check_md_links.main()
            finally:
                sys.argv = original_argv

        assert exit_code == 1
        stderr_output = stderr_capture.getvalue()
        assert stderr_output == ""  # No diagnostics on stderr

        stdout_output = stdout_capture.getvalue().strip()
        data = json.loads(stdout_output)
        assert data["passed"] is False
        assert len(data["broken_links"]) == 1
        bl = data["broken_links"][0]
        assert bl["file"] == "test.md"
        assert bl["line"] == 1
        assert bl["raw_target"] == "missing.md"
        assert bl["resolved_path"] == str((tmp_path / "missing.md").resolve())
        assert data["unlinked_resources"] == []

    def test_json_with_unlinked_resource(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """--json with unlinked resource emits JSON with passed=false and unlinked_resources."""
        md_file = tmp_path / "test.md"
        target_file = tmp_path / "target.md"
        target_file.write_text("# Target\n")
        md_file.write_text("[link](target.md)\n")

        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        monkeypatch.setattr(
            "check_md_links.check_readme_coverage", lambda: (["src/unlinked.md"], 1)
        )

        import io
        import sys
        from contextlib import redirect_stderr, redirect_stdout

        import check_md_links

        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            original_argv = sys.argv
            sys.argv = ["check_md_links.py", "--json"]
            try:
                exit_code = check_md_links.main()
            finally:
                sys.argv = original_argv

        assert exit_code == 1
        stderr_output = stderr_capture.getvalue()
        assert stderr_output == ""  # No diagnostics on stderr

        stdout_output = stdout_capture.getvalue().strip()
        data = json.loads(stdout_output)
        assert data["passed"] is False
        assert data["broken_links"] == []
        assert data["unlinked_resources"] == ["src/unlinked.md"]

    def test_default_output_unaffected(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Default (non-JSON) output is byte-identical to before."""
        md_file = tmp_path / "test.md"
        target_file = tmp_path / "target.md"
        target_file.write_text("# Target\n")
        md_file.write_text("[link](target.md)\n")

        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        monkeypatch.setattr("check_md_links.check_readme_coverage", lambda: ([], 0))

        import sys

        import check_md_links

        original_argv = sys.argv
        sys.argv = ["check_md_links.py"]
        try:
            exit_code = check_md_links.main()
        finally:
            sys.argv = original_argv

        assert exit_code == 0
        captured = capsys.readouterr()
        # Clean run: no findings printed to stdout, nothing on stderr
        assert captured.out == ""
        assert captured.err == ""

    def test_default_output_with_findings(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Default output with findings matches the original format."""
        md_file = tmp_path / "test.md"
        md_file.write_text("[link](missing.md)\n")

        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        monkeypatch.setattr("check_md_links.check_readme_coverage", lambda: ([], 0))

        import sys

        import check_md_links

        original_argv = sys.argv
        sys.argv = ["check_md_links.py"]
        try:
            exit_code = check_md_links.main()
        finally:
            sys.argv = original_argv

        assert exit_code == 1
        captured = capsys.readouterr()
        # Should have the human-readable finding on stdout
        assert "test.md:1: broken-link -> missing.md" in captured.out
        # And the summary on stderr
        assert "1 finding(s)." in captured.err

    def test_exit_codes_identical(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Exit codes are identical in both modes for the same input."""
        # Test with broken link
        md_file = tmp_path / "test.md"
        md_file.write_text("[link](missing.md)\n")

        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        monkeypatch.setattr("check_md_links.check_readme_coverage", lambda: ([], 0))

        import io
        import sys
        from contextlib import redirect_stderr, redirect_stdout

        import check_md_links

        # Non-JSON mode
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        original_argv = sys.argv
        sys.argv = ["check_md_links.py"]
        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exit_code_human = check_md_links.main()
        finally:
            sys.argv = original_argv

        # JSON mode
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        sys.argv = ["check_md_links.py", "--json"]
        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exit_code_json = check_md_links.main()
        finally:
            sys.argv = original_argv

        assert exit_code_human == exit_code_json == 1

        # Test clean tree
        target_file = tmp_path / "target.md"
        target_file.write_text("# Target\n")
        md_file.write_text("[link](target.md)\n")

        # Non-JSON mode
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        sys.argv = ["check_md_links.py"]
        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exit_code_human_clean = check_md_links.main()
        finally:
            sys.argv = original_argv

        # JSON mode
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        sys.argv = ["check_md_links.py", "--json"]
        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exit_code_json_clean = check_md_links.main()
        finally:
            sys.argv = original_argv

        assert exit_code_human_clean == exit_code_json_clean == 0
