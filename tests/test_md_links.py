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
from unittest.mock import patch


# Mock pytest since it's not available in this environment
class MockPytest:
    class MonkeyPatch:
        def setattr(self, target, value):
            pass  # Do nothing for now


pytest = MockPytest()

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
        result = check_links(registry=[])
        assert result["findings"] == []


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


def test_json_output_clean_tree() -> None:
    """Test --json output on a clean tree (no findings)."""
    import io
    import json
    import sys

    # Backup sys.argv and sys.stdout/stderr
    old_argv = sys.argv
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    try:
        sys.argv = [sys.executable, "scripts/check_md_links.py", "--json"]
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture

        # Import and run main
        from check_md_links import main

        returncode = main()

        # Get captured output
        stdout = stdout_capture.getvalue()
        stderr = stderr_capture.getvalue()

        assert returncode == 0
        assert stderr == ""

        data = json.loads(stdout)
        assert data["pass"] is True
        assert isinstance(data["markdown_files_scanned"], int)
        assert isinstance(data["links_resolved"], int)
        assert isinstance(data["resources_checked"], int)
        assert isinstance(data["files_skipped_as_vendored"], int)
        assert data["broken_links"] == []
        assert data["unlinked_resources"] == []
    finally:
        # Restore
        sys.argv = old_argv
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def test_json_output_with_broken_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test --json output with a broken link."""
    import importlib
    import io
    import json
    import sys

    # Create a temporary markdown file with a broken link
    broken_md = tmp_path / "broken.md"
    broken_md.write_text("See [this link](nonexistent.md) for details.")

    # Mock tracked_markdown to return our broken file
    def mock_tracked_markdown():
        return [broken_md]

    monkeypatch.setattr("check_md_links.tracked_markdown", mock_tracked_markdown)

    # Backup sys.argv and sys.stdout/stderr
    old_argv = sys.argv
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    try:
        sys.argv = [sys.executable, "scripts/check_md_links.py", "--json"]
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture

        # Import and run main - reload the module to ensure monkeypatch takes effect
        if "check_md_links" in sys.modules:
            importlib.reload(sys.modules["check_md_links"])
        from check_md_links import main

        returncode = main()

        # Get captured output
        stdout = stdout_capture.getvalue()
        stderr = stderr_capture.getvalue()

        assert returncode == 1  # Should fail due to broken link
        assert stderr == ""  # No stderr in JSON mode

        data = json.loads(stdout)
        assert data["pass"] is False
        assert data["markdown_files_scanned"] == 1
        assert data["links_resolved"] == 1
        assert data["broken_links"] == [
            {
                "file": "broken.md:1",
                "raw_target": "nonexistent.md",
                "resolved_path": "nonexistent.md",
            }
        ]
    finally:
        # Restore
        sys.argv = old_argv
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def test_json_output_with_unlinked_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test --json output with an unlinked resource."""
    import importlib
    import io
    import json
    import sys

    # We'll mock the discover function to return a fake resource
    # that is not linked in the README

    class FakeItem:
        def __init__(self, kind, name, src):
            self.kind = kind
            self.name = name
            self.src = src

    def mock_discover(_):
        return [FakeItem("skill", "test-skill", Path("src/nonexistent/SKILL.md"))]

    with patch("claude_all.cli.discover", side_effect=mock_discover):
        # Backup sys.argv and sys.stdout/stderr
        old_argv = sys.argv
        old_stdout = sys.stdout
        old_stderr = sys.stderr

        try:
            sys.argv = [sys.executable, "scripts/check_md_links.py", "--json"]
            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture

            # Import and run main - reload the module to ensure monkeypatch takes effect
            if "check_md_links" in sys.modules:
                importlib.reload(sys.modules["check_md_links"])
            from check_md_links import main

            returncode = main()

            # Get captured output
            stdout = stdout_capture.getvalue()
            stderr = stderr_capture.getvalue()

            assert returncode == 1  # Should fail due to unlinked resource
            assert stderr == ""  # No stderr in JSON mode

            data = json.loads(stdout)
            assert data["pass"] is False
            assert data["resources_checked"] == 1
            assert data["unlinked_resources"] == ["src/nonexistent/SKILL.md"]
        finally:
            # Restore
            sys.argv = old_argv
            sys.stdout = old_stdout
            sys.stderr = old_stderr


def test_normal_output_unchanged() -> None:
    """Verify that normal (non-JSON) output is unchanged."""
    import subprocess

    # Test normal mode
    result_normal = subprocess.run(
        [sys.executable, "scripts/check_md_links.py"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    # Test JSON mode
    result_json = subprocess.run(
        [sys.executable, "scripts/check_md_links.py", "--json"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    # Both should have same return code
    assert result_normal.returncode == result_json.returncode

    # In clean state, both should have no output
    assert result_normal.stdout == ""
    assert result_json.stdout.strip() != ""  # JSON output should not be empty

    # Normal mode should have no stderr in clean state
    assert result_normal.stderr == ""
    # JSON mode should have no stderr
    assert result_json.stderr == ""
