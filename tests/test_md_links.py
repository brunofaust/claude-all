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

import check_md_links
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


def test_json_clean_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json on a clean tree returns pass=True and zero counts."""
    # Create a simple markdown file with no links
    md_file = tmp_path / "test.md"
    md_file.write_text("# Test\n\nSome text.")

    # Mock tracked_markdown to return our file
    monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])

    # Mock vendored.json to return empty registry
    monkeypatch.setattr("check_md_links.json.loads", lambda x: {"vendored": []})

    # Import and run main with --json
    import sys
    from io import StringIO

    from check_md_links import main

    # Capture stdout and stderr
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StringIO(), StringIO()

    try:
        # Set up argv for --json
        sys.argv = ["check_md_links.py", "--json"]
        result = main()

        # Get output
        stdout_val = sys.stdout.getvalue()
        stderr_val = sys.stderr.getvalue()
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

    # Parse JSON output
    data = json.loads(stdout_val)
    print(f"DEBUG: data = {data}")  # Debug line

    # Assertions
    assert result == 0  # Should return 0 for clean tree
    assert data["pass_fail"] is True
    assert data["counts"]["markdown_files_scanned"] == 1
    assert data["counts"]["links_resolved"] == 0
    assert data["counts"]["resources_checked"] == 0  # No resources discovered in mock
    assert data["counts"]["files_skipped_as_vendored"] == 0
    assert data["broken_links"] == []
    assert data["unlinked_resources"] == []
    # stderr should have findings count (0 findings -> no output)
    assert stderr_val == ""


def test_json_with_broken_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json with a broken link returns pass=False and broken link details."""
    # Create a markdown file with a broken link
    md_file = tmp_path / "test.md"
    md_file.write_text("# Test\n\n[link](missing.md)")

    # Mock tracked_markdown to return our file
    monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])

    # Mock vendored.json to return empty registry
    monkeypatch.setattr("check_md_links.json.loads", lambda x: {"vendored": []})

    # Import and run main with --json
    import sys
    from io import StringIO

    from check_md_links import main

    # Capture stdout and stderr
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StringIO(), StringIO()

    try:
        # Set up argv for --json
        sys.argv = ["check_md_links.py", "--json"]
        result = main()

        # Get output
        stdout_val = sys.stdout.getvalue()
        stderr_val = sys.stderr.getvalue()
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

    # Parse JSON output
    data = json.loads(stdout_val)

    # Assertions
    assert result == 1  # Should return 1 for findings
    assert data["pass_fail"] is False
    assert data["counts"]["markdown_files_scanned"] == 1
    assert data["counts"]["links_resolved"] == 1
    assert data["counts"]["resources_checked"] == 0
    assert data["counts"]["files_skipped_as_vendored"] == 0
    assert len(data["broken_links"]) == 1
    broken_link = data["broken_links"][0]
    assert broken_link["file"] == "test.md"
    assert broken_link["line"] == 2
    assert broken_link["raw_target"] == "missing.md"
    assert broken_link["resolved_path"] == str((tmp_path / "missing.md").resolve())
    assert data["unlinked_resources"] == []
    # stderr should have findings count
    assert "1 finding(s)" in stderr_val


def test_json_with_unlinked_resource(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json with an unlinked resource returns pass=False and unlinked resource details."""
    # We need to mock the discover function to return a resource
    # Create a temporary CLI module to mock
    import types

    mock_cli = types.ModuleType("claude_all.cli")

    # Create a mock item that represents a resource
    mock_item = types.SimpleNamespace()
    mock_item.kind = "skill"
    mock_item.name = "test-skill"
    mock_item.src = tmp_path / "src" / "test-skill" / "SKILL.md"
    mock_item.src.parent.mkdir(parents=True)
    mock_item.src.write_text("# Test Skill")

    # Mock discover to return our item
    def mock_discover(_):
        return [mock_item]

    mock_cli.discover = mock_discover

    # Create a README that does NOT link to our resource
    readme = tmp_path / "README.md"
    readme.write_text("# README\n\nSome content but no link to test-skill.")

    # Create a markdown file (to satisfy the markdown scanning)
    md_file = tmp_path / "test.md"
    md_file.write_text("# Test\n\nSome text.")

    # Mock tracked_markdown to return our markdown file
    monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])

    # Mock vendored.json to return empty registry
    monkeypatch.setattr("check_md_links.json.loads", lambda x: {"vendored": []})

    # Mock sys.path.insert and import of claude_all.cli
    import sys

    original_path_insert = sys.path.insert

    def mock_path_insert(pos, path):
        if "src" in str(path):
            sys.modules["claude_all.cli"] = mock_cli
        return original_path_insert(pos, path)

    monkeypatch.setattr("sys.path.insert", mock_path_insert)

    # Also need to mock the README path in check_readme_coverage functions
    original_readme_path = None

    def mock_check_readme_coverage():
        return [
            f"README.md: undocumented -> {mock_item.kind}/{mock_item.name} "
            f"(add a row linking {mock_item.src.relative_to(tmp_path).as_posix()})"
        ]

    def mock_check_readme_coverage_json():
        return (
            1,
            [
                {
                    "kind": mock_item.kind,
                    "name": mock_item.name,
                    "path": mock_item.src.relative_to(tmp_path).as_posix(),
                }
            ],
        )

    # Patch the functions
    monkeypatch.setattr("check_md_links.check_readme_coverage", mock_check_readme_coverage)
    monkeypatch.setattr(
        "check_md_links.check_readme_coverage_json", mock_check_readme_coverage_json
    )

    # Import and run main with --json
    from io import StringIO

    from check_md_links import main

    # Capture stdout and stderr
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StringIO(), StringIO()

    try:
        # Set up argv for --json
        sys.argv = ["check_md_links.py", "--json"]
        result = main()

        # Get output
        stdout_val = sys.stdout.getvalue()
        stderr_val = sys.stderr.getvalue()
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

    # Parse JSON output
    data = json.loads(stdout_val)

    # Assertions
    assert result == 1  # Should return 1 for findings
    assert data["pass_fail"] is False
    assert data["counts"]["markdown_files_scanned"] == 1
    assert data["counts"]["links_resolved"] == 0
    assert data["counts"]["resources_checked"] == 1
    assert data["counts"]["files_skipped_as_vendored"] == 0
    assert data["broken_links"] == []
    assert len(data["unlinked_resources"]) == 1
    unlinked_resource = data["unlinked_resources"][0]
    assert unlinked_resource["kind"] == "skill"
    assert unlinked_resource["name"] == "test-skill"
    assert unlinked_resource["path"] == "src/test-skill/SKILL.md"
    # stderr should have findings count
    assert "1 finding(s)" in stderr_val


def test_default_output_unaffected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default (non-JSON) output remains byte-identical to today."""
    # Create a markdown file with a broken link
    md_file = tmp_path / "test.md"
    md_file.write_text("# Test\n\n[link](missing.md)\n\n[another](also_missing.md)")

    # Mock tracked_markdown to return our file
    monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])

    # Mock vendored.json to return empty registry
    monkeypatch.setattr("check_md_links.json.loads", lambda x: {"vendored": []})

    # Mock Path.relative_to to work with tmp_path
    original_relative_to = Path.relative_to

    def mock_relative_to(self, other, *args, **kwargs):
        # Make paths relative to tmp_path for testing
        if other == Path(check_md_links.__globals__["ROOT"]):
            return self.relative_to(tmp_path, *args, **kwargs)
        return original_relative_to(self, other, *args, **kwargs)

    monkeypatch.setattr(Path, "relative_to", mock_relative_to)

    # Import and run main without --json (default)
    import sys
    from io import StringIO

    from check_md_links import main

    # Capture stdout and stderr
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StringIO(), StringIO()

    try:
        # Set up argv for default mode
        sys.argv = ["check_md_links.py"]
        result = main()

        # Get output
        stdout_val = sys.stdout.getvalue()
        stderr_val = sys.stderr.getvalue()
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

    # Expected output format (based on existing check_links function)
    expected_lines = [
        "test.md:2: broken-link -> missing.md",
        "test.md:4: broken-link -> also_missing.md",
        "",
        "2 finding(s).",
    ]
    expected_stdout = "\n".join(expected_lines)

    # Assertions
    assert result == 1  # Should return 1 for findings
    assert stdout_val == expected_stdout
    assert "2 finding(s)" in stderr_val

    # Also test clean tree default output
    md_file_clean = tmp_path / "clean.md"
    md_file_clean.write_text("# Clean\n\nNo links here.")
    monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file_clean])

    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = StringIO(), StringIO()

    try:
        sys.argv = ["check_md_links.py"]
        result = main()

        stdout_val = sys.stdout.getvalue()
        stderr_val = sys.stderr.getvalue()
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

    assert result == 0  # Should return 0 for clean tree
    assert stdout_val == ""  # No findings, so no output
    assert stderr_val == ""  # No findings, so no output to stderr
