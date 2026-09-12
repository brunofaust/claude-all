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
import subprocess
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
        findings, _, _, _ = check_links(registry=[])
        assert findings == []


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
    def _make_repo(self, tmp_path: Path) -> Path:
        """Initialize a git repo in tmp_path and return the repo root."""
        repo = tmp_path
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        return repo

    def test_json_clean_tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = self._make_repo(tmp_path)
        # Create a simple markdown file with no links
        md = repo / "test.md"
        md.write_text("# Test\n\nNo links here.")
        # Create vendored.json with empty vendored list
        vendored = repo / "vendored.json"
        vendored.write_text('{"vendored": []}')
        # Create README.md
        readme = repo / "README.md"
        readme.write_text("# README\n")
        # Ensure the markdown file is tracked
        subprocess.run(["git", "add", "test.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)

        # Monkeypatch the checked_markdown function to use our repo
        monkeypatch.setattr("check_md_links.ROOT", repo)
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [repo / "test.md"])

        # Mock discover to return no resources
        class dummy_item:
            pass

        monkeypatch.setattr(
            "check_md_links.cli.discover",
            lambda _: [],
        )

        # Import the main function from check_md_links
        import io
        import sys

        from check_md_links import main

        # Capture stdout and stderr
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            # Run with --json
            sys.argv = ["check_md_links", "--json"]
            exit_code = main()
            output = sys.stdout.getvalue()
            error = sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

        # Parse JSON
        data = json.loads(output)
        assert data["pass"] is True
        assert data["markdown_files_scanned"] == 1
        assert data["links_resolved"] == 0
        assert data["resources_checked"] == 0
        assert data["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert data["unlinked_resources"] == []
        assert exit_code == 0
        # No output to stderr in JSON mode
        assert error == ""

    def test_json_with_broken_link(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = self._make_repo(tmp_path)
        # Create a markdown file with a broken link
        md = repo / "test.md"
        md.write_text("# Test\n\n[link](missing.md)")
        # Create vendored.json with empty vendored list
        vendored = repo / "vendored.json"
        vendored.write_text('{"vendored": []}')
        # Create README.md
        readme = repo / "README.md"
        readme.write_text("# README\n")
        # Track the markdown file
        subprocess.run(["git", "add", "test.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)

        monkeypatch.setattr("check_md_links.ROOT", repo)
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [repo / "test.md"])

        # Mock discover to return no resources
        monkeypatch.setattr(
            "check_md_links.cli.discover",
            lambda _: [],
        )

        import io
        import sys

        from check_md_links import main

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            sys.argv = ["check_md_links", "--json"]
            exit_code = main()
            output = sys.stdout.getvalue()
            error = sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

        data = json.loads(output)
        assert data["pass"] is False
        assert data["markdown_files_scanned"] == 1
        assert data["links_resolved"] == 1
        assert data["resources_checked"] == 0
        assert data["files_skipped_as_vendored"] == 0
        assert len(data["broken_links"]) == 1
        link = data["broken_links"][0]
        assert link["file"] == "test.md"
        assert link["raw_link_target"] == "missing.md"
        # The resolved path should be the absolute path to missing.md in the repo
        assert link["resolved_path"] == str((repo / "missing.md").resolve())
        assert data["unlinked_resources"] == []
        assert exit_code == 1
        # No output to stderr in JSON mode
        assert error == ""

    def test_json_with_unlinked_resource(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = self._make_repo(tmp_path)
        # Create a markdown file with no links (to avoid broken links)
        md = repo / "test.md"
        md.write_text("# Test\n\nNo links.")
        # Create vendored.json with empty vendored list
        vendored = repo / "vendored.json"
        vendored.write_text('{"vendored": []}')
        # Create README.md (empty, so no resources linked)
        readme = repo / "README.md"
        readme.write_text("# README\n")
        # Track the markdown file
        subprocess.run(["git", "add", "test.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)

        monkeypatch.setattr("check_md_links.ROOT", repo)
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [repo / "test.md"])

        # Create a dummy resource
        class Item:
            def __init__(self, kind, name, src):
                self.kind = kind
                self.name = name
                self.src = src

        item = Item("skill", "test-skill", repo / "src" / "test-skill" / "SKILL.md")
        # We don't actually need to create the file, just the path
        monkeypatch.setattr(
            "check_md_links.cli.discover",
            lambda _: [item],
        )

        import io
        import sys

        from check_md_links import main

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            sys.argv = ["check_md_links", "--json"]
            exit_code = main()
            output = sys.stdout.getvalue()
            error = sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

        data = json.loads(output)
        assert data["pass"] is False
        assert data["markdown_files_scanned"] == 1
        assert data["links_resolved"] == 0
        assert data["resources_checked"] == 1
        assert data["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert len(data["unlinked_resources"]) == 1
        # The unlinked resource path should be relative to the repo root
        assert data["unlinked_resources"][0] == "src/test-skill/SKILL.md"
        assert exit_code == 1
        assert error == ""

    def test_non_json_output_unaffected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ensure that without --json, the output and exit code are unchanged."""
        repo = self._make_repo(tmp_path)
        # Create a markdown file with a broken link and an unlinked resource scenario
        md = repo / "test.md"
        md.write_text("# Test\n\n[link](missing.md)")
        vendored = repo / "vendored.json"
        vendored.write_text('{"vendored": []}')
        readme = repo / "README.md"
        readme.write_text("# README\n")
        subprocess.run(["git", "add", "test.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True)

        monkeypatch.setattr("check_md_links.ROOT", repo)
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [repo / "test.md"])

        class Item:
            def __init__(self, kind, name, src):
                self.kind = kind
                self.name = name
                self.src = src

        item = Item("skill", "test-skill", repo / "src" / "test-skill" / "SKILL.md")
        monkeypatch.setattr(
            "check_md_links.cli.discover",
            lambda _: [item],
        )

        import io
        import sys

        from check_md_links import main

        # Test without --json
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            sys.argv = ["check_md_links"]
            exit_code = main()
            stdout_out = sys.stdout.getvalue()
            stderr_out = sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

        # Expect human-readable output: one line for the broken link and one for
        # the unlinked resource
        # The broken link line: "test.md:1: broken-link -> missing.md"
        # The unlinked resource line: "README.md: undocumented ->
        # skill/test-skill (add a row linking src/test-skill/SKILL.md)"
        # Note: the line number may vary because we stripped code blocks? There
        # are no code blocks, so line 2? Let's compute:
        # The markdown content:
        # Line 1: '# Test'
        # Line 2: ''
        # Line 3: '[link](missing.md)'
        # So the link is on line 3.
        # However, the strip_code_blocks function does not change line numbers
        # for non-fenced lines.
        # So the line number should be 3.
        expected_lines = [
            "test.md:3: broken-link -> missing.md",
            "README.md: undocumented -> skill/test-skill (add a row linking "
            "src/test-skill/SKILL.md)",
        ]
        # The output may have the lines in either order? The script first
        # outputs broken links then unlinked resources.
        # So we expect the broken link first, then the unlinked resource.
        actual_lines = [line.strip() for line in stdout_out.strip().splitlines() if line.strip()]
        assert actual_lines == expected_lines
        # The stderr should have the count line: "2 finding(s)."
        assert stderr_out.strip() == "2 finding(s)."
        assert exit_code == 1

        # Now test with --json on the same setup to ensure JSON mode works
        # (we already tested in other tests, but we can do a quick check)
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            sys.argv = ["check_md_links", "--json"]
            exit_code_json = main()
            json_out = sys.stdout.getvalue()
            stderr_json = sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

        data = json.loads(json_out)
        assert data["pass"] is False
        assert data["markdown_files_scanned"] == 1
        assert data["links_resolved"] == 1
        assert data["resources_checked"] == 1
        assert data["files_skipped_as_vendored"] == 0
        assert len(data["broken_links"]) == 1
        assert len(data["unlinked_resources"]) == 1
        assert exit_code_json == 1
        assert stderr_json == ""
