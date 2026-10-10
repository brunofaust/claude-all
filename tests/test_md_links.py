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


def test_json_output_clean_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Test --json output on a clean tree with no findings."""
    # Create a temporary directory structure
    (tmp_path / "README.md").write_text("# Test\n\nThis is a test.")

    # Mock vendored.json to have no vendored entries
    vendored_data: dict = {"vendored": []}
    monkeypatch.setattr("check_md_links.ROOT", tmp_path)  # Change ROOT to temp dir for this test
    monkeypatch.setattr(
        "builtins.open", lambda *args, **kwargs: mock_open_vendored(vendored_data, *args, **kwargs)
    )

    # Mock discover to return no resources
    class MockItem:
        def __init__(self, kind: str, name: str, src: Path) -> None:
            self.kind = kind
            self.name = name
            self.src = src

    def mock_discover(_args: list) -> list:
        return []

    # Mock git ls-files to return only README.md
    def mock_tracked_markdown():
        return [tmp_path / "README.md"]

    monkeypatch.setattr("check_md_links.tracked_markdown", mock_tracked_markdown)

    # Mock _check_readme_coverage_internal to return no resources
    def mock_check_readme_coverage_internal(_registry: list[dict]) -> tuple[list[dict], dict]:
        return ([], {"resources_checked": 0})

    monkeypatch.setattr(
        "check_md_links._check_readme_coverage_internal", mock_check_readme_coverage_internal
    )

    # Test --json output
    import sys

    from check_md_links import main

    # Save original argv
    old_argv = sys.argv
    try:
        sys.argv = ["check_md_links.py", "--json"]
        # Change working directory to temp path
        monkeypatch.chdir(tmp_path)
        # Run main
        result = main()
    finally:
        sys.argv = old_argv

    # Should return 0 (no findings)
    assert result == 0

    # Capture stdout and stderr
    captured = capsys.readouterr()
    stdout = captured.out.strip()
    stderr = captured.err

    # Should have no stderr output (no findings message)
    assert stderr == ""

    # Should be valid JSON
    data = json.loads(stdout)

    # Check structure
    assert data["pass"] is True
    assert data["counts"]["markdown_files_scanned"] == 1  # README.md
    assert data["counts"]["links_resolved"] == 0
    assert data["counts"]["resources_checked"] == 0
    assert data["counts"]["files_skipped_as_vendored"] == 0
    assert data["broken_links"] == []
    assert data["unlinked_resources"] == []


def test_json_output_with_broken_link(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Test --json output when there's a broken link."""
    # Create a markdown file with a broken link
    (tmp_path / "README.md").write_text("# Test\n\nSee [link](missing.md) for details.")
    (tmp_path / "other.md").write_text("# Other\n\nNo links here.")

    # Mock vendored.json to have no vendored entries
    vendored_data: dict = {"vendored": []}
    monkeypatch.setattr("check_md_links.ROOT", tmp_path)
    monkeypatch.setattr(
        "builtins.open", lambda *args, **kwargs: mock_open_vendored(vendored_data, *args, **kwargs)
    )

    # Mock discover to return no resources
    class MockItem:
        def __init__(self, kind: str, name: str, src: Path) -> None:
            self.kind = kind
            self.name = name
            self.src = src

    def mock_discover(_args: list) -> list:
        return []

    # Mock git ls-files to return both markdown files
    def mock_tracked_markdown():
        return [tmp_path / "README.md", tmp_path / "other.md"]

    monkeypatch.setattr("check_md_links.tracked_markdown", mock_tracked_markdown)

    # Mock _check_readme_coverage_internal to return no resources
    def mock_check_readme_coverage_internal(_registry: list[dict]) -> tuple[list[dict], dict]:
        return ([], {"resources_checked": 0})

    monkeypatch.setattr(
        "check_md_links._check_readme_coverage_internal", mock_check_readme_coverage_internal
    )

    # Test --json output
    import sys

    from check_md_links import main

    old_argv = sys.argv
    try:
        sys.argv = ["check_md_links.py", "--json"]
        monkeypatch.chdir(tmp_path)
        result = main()
    finally:
        sys.argv = old_argv

    # Should return 1 (has findings)
    assert result == 1

    # Capture stdout and stderr
    captured = capsys.readouterr()
    stdout = captured.out.strip()
    stderr = captured.err

    # Should have no stderr output (the findings count goes to stderr in non-JSON mode only)
    # In JSON mode, diagnostics should go to stderr but we don't have any beyond the count line
    # Actually, in our implementation, we only print to stderr in non-JSON mode
    assert stderr == ""

    # Should be valid JSON
    data = json.loads(stdout)

    # Check structure
    assert data["pass"] is False
    assert data["counts"]["markdown_files_scanned"] == 2  # Both files
    assert data["counts"]["links_resolved"] == 1  # One link in README.md
    assert data["counts"]["resources_checked"] == 0
    assert data["counts"]["files_skipped_as_vendored"] == 0
    assert len(data["broken_links"]) == 1
    broken_link = data["broken_links"][0]
    assert broken_link["file"] == "README.md"
    assert broken_link["line"] == 2  # Line number of the link
    assert broken_link["target"] == "missing.md"
    assert broken_link["resolved_path"] == str((tmp_path / "missing.md").resolve())
    assert data["unlinked_resources"] == []


def test_json_output_with_unlinked_resource(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Test --json output when there's an unlinked resource."""
    # Create a README that doesn't link to a resource
    (tmp_path / "README.md").write_text("# Test\n\nSome content but no link to resource.")

    # Mock vendored.json to have no vendored entries
    vendored_data: dict = {"vendored": []}
    monkeypatch.setattr("check_md_links.ROOT", tmp_path)
    monkeypatch.setattr(
        "builtins.open", lambda *args, **kwargs: mock_open_vendored(vendored_data, *args, **kwargs)
    )

    # Mock discover to return no resources
    class MockItem:
        def __init__(self, kind: str, name: str, src: Path) -> None:
            self.kind = kind
            self.name = name
            self.src = src

    def mock_discover(_args: list) -> list:
        return []

    # Mock git ls-files to return only README.md
    def mock_tracked_markdown():
        return [tmp_path / "README.md"]

    monkeypatch.setattr("check_md_links.tracked_markdown", mock_tracked_markdown)

    # Mock _check_readme_coverage_internal to return an unlinked resource
    def mock_check_readme_coverage_internal(_registry: list[dict]) -> tuple[list[dict], dict]:
        return (
            [{"src": "src/test-skill/SKILL.md", "kind": "skill", "name": "test-skill"}],
            {"resources_checked": 1},
        )

    monkeypatch.setattr(
        "check_md_links._check_readme_coverage_internal", mock_check_readme_coverage_internal
    )

    # Test --json output
    import sys

    from check_md_links import main

    old_argv = sys.argv
    try:
        sys.argv = ["check_md_links.py", "--json"]
        monkeypatch.chdir(tmp_path)
        result = main()
    finally:
        sys.argv = old_argv

    # Should return 1 (has findings)
    assert result == 1

    # Capture stdout and stderr
    captured = capsys.readouterr()
    stdout = captured.out.strip()
    stderr = captured.err

    # Should have no stderr output
    assert stderr == ""

    # Should be valid JSON
    data = json.loads(stdout)

    # Check structure
    assert data["pass"] is False
    assert data["counts"]["markdown_files_scanned"] == 1  # README.md
    assert data["counts"]["links_resolved"] == 0
    assert data["counts"]["resources_checked"] == 1  # One resource discovered
    assert data["counts"]["files_skipped_as_vendored"] == 0
    assert data["broken_links"] == []
    assert len(data["unlinked_resources"]) == 1
    # The unlinked resource should be the src path relative to repo root
    assert data["unlinked_resources"][0] == "src/test-skill/SKILL.md"


def mock_open_vendored(mock_data: dict, *args, **kwargs):
    """Mock open function to return vendored.json data when that file is requested."""
    if len(args) > 0 and "vendored.json" in str(args[0]):
        from io import StringIO

        return StringIO(json.dumps(mock_data))
    # For all other files, use the real open
    return open(*args, **kwargs)
