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
        findings, _ = check_links(registry=[])
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


def test_json_output_clean_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json on a clean tree should show zero findings and counts."""
    # Mock a simple scenario with no markdown files
    monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [])
    # Mock discover to return no items (imported from claude_all.cli inside check_readme_coverage)
    monkeypatch.setattr("claude_all.cli.discover", lambda _: [])

    # Test JSON output
    import sys
    from io import StringIO

    old_argv = sys.argv
    sys.argv = ["check_md_links.py", "--json"]
    old_stdout = sys.stdout
    sys.stdout = StringIO()

    try:
        from check_md_links import main

        result = main()
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        sys.argv = old_argv

        assert result == 0  # Should pass
        data = json.loads(output)
        assert data["passed"] is True
        assert data["markdown_files_scanned"] == 0
        assert data["links_inspected"] == 0
        assert data["resources_checked"] == 0
        assert data["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert data["unlinked_resources"] == []
    finally:
        sys.stdout = old_stdout
        sys.argv = old_argv


def test_json_output_with_broken_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json with a broken link should show the broken link in output."""
    # Create a mock markdown file with a broken link
    md_file = tmp_path / "test.md"
    md_file.write_text("See [broken link](missing.md) for details.\n")

    # Mock tracked_markdown to return our file
    monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
    # Mock is_vendored to return False (not vendored)
    monkeypatch.setattr("check_md_links.is_vendored", lambda p, r: False)
    # Mock the discover function inside check_md_links module where it's imported
    monkeypatch.setattr("check_md_links.discover", lambda _: [])

    # Test JSON output
    import sys
    from io import StringIO

    old_argv = sys.argv
    sys.argv = ["check_md_links.py", "--json"]
    old_stdout = sys.stdout
    sys.stdout = StringIO()

    try:
        from check_md_links import main

        result = main()
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        sys.argv = old_argv

        assert result == 1  # Should fail due to broken link
        data = json.loads(output)
        assert data["passed"] is False
        assert data["markdown_files_scanned"] == 1
        assert data["links_inspected"] == 1
        assert data["resources_checked"] == 0
        assert data["files_skipped_as_vendored"] == 0
        assert len(data["broken_links"]) == 1
        broken_link = data["broken_links"][0]
        assert broken_link["target"] == "missing.md"
        assert "test.md" in broken_link["file"]
        assert data["unlinked_resources"] == []
    finally:
        sys.stdout = old_stdout
        sys.argv = old_argv


def test_json_output_with_unlinked_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--json with an unlinked resource should show the resource in output."""

    # Mock an item that would be discovered but not linked in README
    class MockItem:
        def __init__(self):
            self.kind = "skill"
            self.name = "test-skill"
            self.src = tmp_path / "src" / "test-skill" / "SKILL.md"

    # Mock tracked_markdown to return empty (no markdown files to check links)
    monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [])
    # Mock the discover function inside check_md_links module where it's imported
    monkeypatch.setattr("check_md_links.discover", lambda _: [MockItem()])
    # Mock README.md to not contain the link
    monkeypatch.setattr("check_md_links.ROOT", tmp_path)
    readme_file = tmp_path / "README.md"
    readme_file.write_text("# Test README\n\nNo links here.\n")

    # Test JSON output
    import sys
    from io import StringIO

    old_argv = sys.argv
    sys.argv = ["check_md_links.py", "--json"]
    old_stdout = sys.stdout
    sys.stdout = StringIO()

    try:
        from check_md_links import main

        result = main()
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout
        sys.argv = old_argv

        assert result == 1  # Should fail due to unlinked resource
        data = json.loads(output)
        assert data["passed"] is False
        assert data["markdown_files_scanned"] == 0
        assert data["links_inspected"] == 0
        assert data["resources_checked"] == 1
        assert data["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert len(data["unlinked_resources"]) == 1
        resource = data["unlinked_resources"][0]
        assert resource["kind"] == "skill"
        assert resource["name"] == "test-skill"
        assert "src/test-skill/SKILL.md" in resource["path"]
    finally:
        sys.stdout = old_stdout
        sys.argv = old_argv


def test_default_output_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that default (non-JSON) output is unaffected by the --json flag addition."""
    # Create a mock markdown file with a broken link
    md_file = tmp_path / "test.md"
    md_file.write_text("See [broken link](missing.md) for details.\n")

    # Mock tracked_markdown to return our file
    monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
    # Mock is_vendored to return False (not vendored)
    monkeypatch.setattr("check_md_links.is_vendored", lambda p, r: False)
    # Mock the discover function inside check_md_links module where it's imported
    monkeypatch.setattr("check_md_links.discover", lambda _: [])

    # Test default output (no --json flag)
    import sys
    from io import StringIO

    old_argv = sys.argv
    sys.argv = ["check_md_links.py"]  # No --json flag
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = StringIO()
    sys.stderr = StringIO()

    try:
        from check_md_links import main

        result = main()
        stdout_output = sys.stdout.getvalue()
        stderr_output = sys.stderr.getvalue()
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        sys.argv = old_argv

        assert result == 1  # Should fail due to broken link
        # Should print the finding to stdout
        assert "test.md:1: broken-link -> missing.md" in stdout_output
        # Should print count to stderr
        assert "1 finding(s)." in stderr_output
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        sys.argv = old_argv
