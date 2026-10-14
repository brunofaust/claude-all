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


# Tests for the new --json functionality
class TestJsonOutput:
    def test_json_clean_tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test --json output on a clean tree with no issues."""
        # Set up a temporary git repo with clean markdown files
        monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")

        # Create a simple markdown file with no broken links
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test\n\nThis is a [link](other.md).\n")

        other_file = tmp_path / "other.md"
        other_file.write_text("# Other\n\nContent.\n")

        # Mock git ls-files to return our test files
        def mock_tracked_markdown():
            return [md_file, other_file]

        monkeypatch.setattr("check_md_links.tracked_markdown", mock_tracked_markdown)

        # Mock vendored.json to return empty registry
        original_read_text = Path.read_text

        def mock_read_text(self, *args, **kwargs):
            if str(self).endswith("vendored.json"):
                return '{"vendored": []}'
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", mock_read_text)

        # Mock discover to return empty resources (so no README coverage issues)
        def mock_discover(_):
            return []

        monkeypatch.setattr("check_md_links.discover", mock_discover)
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Initialize git repo
        import subprocess

        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], check=True, capture_output=True)

        # Test JSON output
        sys.argv = ["check_md_links.py", "--json"]
        result = main()

        # Should return 0 (success)
        assert result == 0

    def test_json_with_broken_link(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test --json output with a broken link."""
        # Set up a temporary git repo with a broken link
        monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")

        # Create a markdown file with a broken link
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test\n\nThis is a [broken link](nonexistent.md).\n")

        # Mock git ls-files to return our test file
        def mock_tracked_markdown():
            return [md_file]

        monkeypatch.setattr("check_md_links.tracked_markdown", mock_tracked_markdown)

        # Mock vendored.json to return empty registry
        original_read_text = Path.read_text

        def mock_read_text(self, *args, **kwargs):
            if str(self).endswith("vendored.json"):
                return '{"vendored": []}'
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", mock_read_text)

        # Mock discover to return empty resources
        def mock_discover(_):
            return []

        monkeypatch.setattr("check_md_links.claude_all.cli.discover", mock_discover)

        # Import and test the structured functions directly
        from check_md_links import check_links_structured, check_readme_coverage_structured

        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Initialize git repo
        import subprocess

        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], check=True, capture_output=True)

        # Test the structured link checking
        registry: list[dict] = []
        scanned_files, links_resolved, broken_links, skipped_vendored = check_links_structured(
            registry
        )
        resources_checked, unlinked_resources = check_readme_coverage_structured()

        # Verify we found the broken link
        assert scanned_files == 1
        assert links_resolved == 1
        assert len(broken_links) == 1
        assert broken_links[0]["target"] == "nonexistent.md"
        assert broken_links[0]["file"] == md_file
        assert broken_links[0]["line"] == 2  # Line 2 in the file

        # Verify no resources issues
        assert resources_checked == 0
        assert len(unlinked_resources) == 0
        assert skipped_vendored == 0

    def test_json_with_unlinked_resource(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test --json output with an unlinked resource."""
        # Set up a temporary git repo
        monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")

        # Create a simple markdown file (no links)
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test\n\nJust some content.\n")

        # Mock git ls-files to return our test file
        def mock_tracked_markdown():
            return [md_file]

        monkeypatch.setattr("check_md_links.tracked_markdown", mock_tracked_markdown)

        # Mock vendored.json to return empty registry
        original_read_text = Path.read_text

        def mock_read_text(self, *args, **kwargs):
            if str(self).endswith("vendored.json"):
                return '{"vendored": []}'
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", mock_read_text)

        # Mock discover to return a resource that's not linked from README
        class MockResource:
            def __init__(self, kind, name, src):
                self.kind = kind
                self.name = name
                self.src = src

        resource_file = tmp_path / "src" / "myskill" / "SKILL.md"
        resource_file.parent.mkdir(parents=True, exist_ok=True)
        resource_file.write_text("# My Skill\n\nContent.\n")

        def mock_discover(_):
            return [MockResource("skill", "myskill", resource_file)]

        monkeypatch.setattr("check_md_links.claude_all.cli.discover", mock_discover)

        # Create a README that does NOT link to our resource
        readme_file = tmp_path / "README.md"
        readme_file.write_text("# README\n\nSome content but no link to myskill.\n")

        # Import and test the structured functions directly
        from check_md_links import check_links_structured, check_readme_coverage_structured

        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Initialize git repo
        import subprocess

        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], check=True, capture_output=True)

        # Test the structured link checking
        registry: list[dict] = []
        scanned_files, links_resolved, broken_links, skipped_vendored = check_links_structured(
            registry
        )
        resources_checked, unlinked_resources = check_readme_coverage_structured()

        # Verify no link issues
        assert scanned_files == 1
        assert links_resolved == 0
        assert len(broken_links) == 0
        assert skipped_vendored == 0

        # Verify we found the unlinked resource
        assert resources_checked == 1
        assert len(unlinked_resources) == 1
        assert unlinked_resources[0] == "src/myskill/SKILL.md"

    def test_default_output_unaffected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that default (non-JSON) output is unchanged."""
        # Set up a temporary git repo with a broken link
        monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")

        # Create a markdown file with a broken link
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test\n\nThis is a [broken link](nonexistent.md).\n")

        # Mock git ls-files to return our test file
        def mock_tracked_markdown():
            return [md_file]

        monkeypatch.setattr("check_md_links.tracked_markdown", mock_tracked_markdown)

        # Mock vendored.json to return empty registry
        original_read_text = Path.read_text

        def mock_read_text(self, *args, **kwargs):
            if str(self).endswith("vendored.json"):
                return '{"vendored": []}'
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", mock_read_text)

        # Mock discover to return empty resources
        def mock_discover(_):
            return []

        monkeypatch.setattr("check_md_links.claude_all.cli.discover", mock_discover)

        # Import and test the main function
        from check_md_links import main

        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Initialize git repo
        import subprocess

        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], check=True, capture_output=True)

        # Test default output (should be unchanged)
        sys.argv = ["check_md_links.py"]
        result = main()

        # Should return 1 (failure due to broken link)
        assert result == 1

        # Test JSON output (should also return 1 for same issue)
        sys.argv = ["check_md_links.py", "--json"]
        result_json = main()

        # Should also return 1 (same exit code)
        assert result_json == 1
