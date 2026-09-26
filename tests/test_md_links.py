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
        broken_links, counts = check_links(registry=[])
        assert broken_links == []
        assert counts["markdown_files_scanned"] == 0
        assert counts["links_resolved"] == 0
        assert counts["files_skipped_as_vendored"] == 0


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


# JSON output mode tests
class TestJsonOutput:
    """Tests for the --json flag output mode."""

    def test_json_clean_tree(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """JSON output on a clean tree (no broken links, all resources linked)."""
        # Mock tracked_markdown to return empty list (no files to check)
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [])
        # Mock discover to return empty list (no resources to check)
        monkeypatch.setattr("check_md_links.discover", lambda _: [])

        # Run with --json flag
        import io
        import sys

        from check_md_links import main

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            exit_code = main(["--json"])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        assert exit_code == 0
        result = json.loads(output.strip())
        assert result["pass"] is True
        assert result["counts"]["markdown_files_scanned"] == 0
        assert result["counts"]["links_resolved"] == 0
        assert result["counts"]["resources_checked"] == 0
        assert result["counts"]["files_skipped_as_vendored"] == 0
        assert result["broken_links"] == []
        assert result["unlinked_resources"] == []

    def test_json_with_broken_link(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """JSON output when a broken link is found."""
        # Create a temporary markdown file with a broken link
        md_file = tmp_path / "test.md"
        md_file.write_text("[broken](does_not_exist.md)\n")

        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        # Mock discover to return empty list
        monkeypatch.setattr("check_md_links.discover", lambda _: [])

        import io
        import sys

        from check_md_links import main

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            exit_code = main(["--json"])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        assert exit_code == 1
        result = json.loads(output.strip())
        assert result["pass"] is False
        assert result["counts"]["markdown_files_scanned"] == 1
        assert result["counts"]["links_resolved"] == 1
        assert len(result["broken_links"]) == 1
        bl = result["broken_links"][0]
        assert bl["file"] == "test.md"
        assert bl["line"] == 1
        assert bl["target"] == "does_not_exist.md"
        assert "does_not_exist.md" in bl["resolved_path"]
        assert result["unlinked_resources"] == []

    def test_json_with_unlinked_resource(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """JSON output when an unlinked resource is found."""
        # Mock tracked_markdown to return empty list (no link checking)
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [])

        # Create a mock resource that is not linked
        from types import SimpleNamespace

        mock_resource = SimpleNamespace(
            kind="skill",
            name="test-skill",
            src=tmp_path / "skills" / "test-skill" / "SKILL.md",
        )
        mock_resource.src.parent.mkdir(parents=True, exist_ok=True)
        mock_resource.src.write_text("---\nname: test-skill\n---\n")

        monkeypatch.setattr("check_md_links.discover", lambda _: [mock_resource])
        # Mock README to not contain the link
        monkeypatch.setattr(
            "check_md_links.Path.read_text",
            lambda self, *a, **kw: (
                "# README\n" if self.name == "README.md" else mock_resource.src.read_text()
            ),
        )

        import io
        import sys

        from check_md_links import main

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            exit_code = main(["--json"])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        assert exit_code == 1
        result = json.loads(output.strip())
        assert result["pass"] is False
        assert result["counts"]["markdown_files_scanned"] == 0
        assert result["counts"]["links_resolved"] == 0
        assert result["counts"]["resources_checked"] == 1
        assert len(result["unlinked_resources"]) == 1
        assert result["unlinked_resources"][0].endswith("SKILL.md")
        assert result["broken_links"] == []

    def test_default_output_unaffected(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Default (non-JSON) output is unchanged."""
        # Create a temporary markdown file with a broken link
        md_file = tmp_path / "test.md"
        md_file.write_text("[broken](does_not_exist.md)\n")

        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setattr("check_md_links.discover", lambda _: [])

        import io
        import sys

        from check_md_links import main

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            exit_code = main([])  # No --json flag
            stdout_output = sys.stdout.getvalue()
            stderr_output = sys.stderr.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        assert exit_code == 1
        # Human-readable output should contain the finding
        assert "test.md:1: broken-link -> does_not_exist.md" in stdout_output
        assert "1 finding(s)." in stderr_output
        # Should NOT be valid JSON
        import json

        try:
            json.loads(stdout_output.strip())
            assert False, "Default output should not be JSON"
        except json.JSONDecodeError:
            pass  # Expected

    def test_json_exit_code_matches_human(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Exit codes are identical in both modes for the same input."""
        # Test with clean tree
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [])
        monkeypatch.setattr("check_md_links.discover", lambda _: [])

        import io
        import sys

        from check_md_links import main

        # JSON mode
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            json_exit = main(["--json"])
        finally:
            sys.stdout = old_stdout

        # Human mode
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            human_exit = main([])
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        assert json_exit == human_exit == 0

        # Test with broken link
        md_file = tmp_path / "test.md"
        md_file.write_text("[broken](does_not_exist.md)\n")
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])

        # JSON mode
        sys.stdout = io.StringIO()
        try:
            json_exit = main(["--json"])
        finally:
            sys.stdout = old_stdout

        # Human mode
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            human_exit = main([])
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        assert json_exit == human_exit == 1
