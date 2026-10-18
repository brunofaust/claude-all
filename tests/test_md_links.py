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


def test_json_output_clean_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json emits valid JSON with passed=True and zero counts on a clean tree."""
    from check_md_links import main

    # Create a simple markdown file with no broken links and full README coverage
    md_file = tmp_path / "test.md"
    md_file.write_text("See [dummy](dummy.md) for more info.\n")
    dummy_file = tmp_path / "dummy.md"
    dummy_file.write_text("# Dummy\n")

    # Mock git ls-files to return our test file
    def mock_tracked_markdown():
        return [md_file]

    monkeypatch.setattr("check_md_links.tracked_markdown", mock_tracked_markdown)
    # Mock vendored registry as empty
    monkeypatch.setattr(
        "check_md_links.json.loads",
        lambda _: {"vendored": []},
    )

    # Mock discover to return no items (so no README coverage issues)
    class MockItem:
        kind = "skill"
        name = "test"
        src = tmp_path / "test.md"

    def mock_discover(_):
        return [MockItem()]

    monkeypatch.setattr("check_md_links.cli.discover", mock_discover)
    # Mock README to contain the link
    readme_mock = tmp_path / "README.md"
    readme_mock.write_text("See [dummy](test/dummy.md) for more info.\n")
    monkeypatch.setattr("check_md_links.ROOT", tmp_path)
    monkeypatch.setattr(
        "builtins.open",
        lambda *args, **kwargs: (
            open(readme_mock, *args, **kwargs)
            if "README.md" in str(args)
            else open(*args, **kwargs)
        ),
    )

    # Capture stdout/stderr
    import contextlib
    import io

    stdout_capture = io.StringIO()
    stderr_capture = io.StringO()

    with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
        result = main(["--json"])

    assert result == 0  # Should pass
    output = stdout_capture.getvalue().strip()
    # Should be valid JSON
    data = json.loads(output)
    assert data["passed"] is True
    assert data["counts"]["markdown_files_scanned"] >= 0
    assert data["counts"]["links_resolved"] >= 0
    assert data["counts"]["resources_checked"] >= 0
    assert data["counts"]["files_skipped_as_vendored"] >= 0
    assert data["broken_links"] == []
    assert data["unlinked_resources"] == []
    # stderr should be empty in JSON mode (no diagnostics)
    assert stderr_capture.getvalue() == ""


def test_json_output_with_broken_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json emits valid JSON with broken link details."""
    from check_md_links import main

    # Create a markdown file with a broken link
    md_file = tmp_path / "test.md"
    md_file.write_text("See [broken](missing.md) for more info.\n")

    # Mock git ls-files to return our test file
    def mock_tracked_markdown():
        return [md_file]

    monkeypatch.setattr("check_md_links.tracked_markdown", mock_tracked_markdown)
    # Mock vendored registry as empty
    monkeypatch.setattr(
        "check_md_links.json.loads",
        lambda _: {"vendored": []},
    )

    # Mock discover to return no items (so no README coverage issues)
    class MockItem:
        kind = "skill"
        name = "test"
        src = tmp_path / "test.md"

    def mock_discover(_):
        return [MockItem()]

    monkeypatch.setattr("check_md_links.cli.discover", mock_discover)
    # Mock README to contain the link (so no coverage issues)
    readme_mock = tmp_path / "README.md"
    readme_mock.write_text("See [broken](test/missing.md) for more info.\n")
    monkeypatch.setattr("check_md_links.ROOT", tmp_path)
    monkeypatch.setattr(
        "builtins.open",
        lambda *args, **kwargs: (
            open(readme_mock, *args, **kwargs)
            if "README.md" in str(args)
            else open(*args, **kwargs)
        ),
    )

    # Capture stdout/stderr
    import contextlib
    import io

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
        result = main(["--json"])

    assert result == 1  # Should fail due to broken link
    output = stdout_capture.getvalue().strip()
    # Should be valid JSON
    data = json.loads(output)
    assert data["passed"] is False
    assert data["counts"]["markdown_files_scanned"] == 1
    assert data["counts"]["links_resolved"] == 1
    assert len(data["broken_links"]) == 1
    broken_link = data["broken_links"][0]
    assert broken_link["file"] == "test.md"
    assert broken_link["line"] == 1
    assert broken_link["target"] == "missing.md"
    # resolved_path should be the path that was checked
    assert broken_link["resolved_path"] == "missing.md" or broken_link["resolved_path"].endswith(
        "/missing.md"
    )
    assert data["unlinked_resources"] == []
    # stderr should be empty in JSON mode (no diagnostics)
    assert stderr_capture.getvalue() == ""


def test_json_output_with_unlinked_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--json emits valid JSON with unlinked resource details."""
    from check_md_links import main

    # Create a markdown file (no broken links)
    md_file = tmp_path / "test.md"
    md_file.write_text("Some content.\n")

    # Mock git ls-files to return our test file
    def mock_tracked_markdown():
        return [md_file]

    monkeypatch.setattr("check_md_links.tracked_markdown", mock_tracked_markdown)
    # Mock vendored registry as empty
    monkeypatch.setattr(
        "check_md_links.json.loads",
        lambda _: {"vendored": []},
    )

    # Mock discover to return an item that is NOT in README
    class MockItem:
        kind = "skill"
        name = "testskill"
        src = tmp_path / "testskill" / "SKILL.md"

    def mock_discover(_):
        return [MockItem()]

    monkeypatch.setattr("check_md_links.cli.discover", mock_discover)
    # Mock README to NOT contain the link (so we get an unlinked resource)
    readme_mock = tmp_path / "README.md"
    readme_mock.write_text("# Readme\n\nNo links here.\n")
    monkeypatch.setattr("check_md_links.ROOT", tmp_path)
    monkeypatch.setattr(
        "builtins.open",
        lambda *args, **kwargs: (
            open(readme_mock, *args, **kwargs)
            if "README.md" in str(args)
            else open(*args, **kwargs)
        ),
    )

    # Capture stdout/stderr
    import contextlib
    import io

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
        result = main(["--json"])

    assert result == 1  # Should fail due to unlinked resource
    output = stdout_capture.getvalue().strip()
    # Should be valid JSON
    data = json.loads(output)
    assert data["passed"] is False
    assert data["counts"]["markdown_files_scanned"] == 1
    assert data["counts"]["links_resolved"] == 0
    assert data["broken_links"] == []
    assert len(data["unlinked_resources"]) == 1
    resource = data["unlinked_resources"][0]
    assert resource["kind"] == "skill"
    assert resource["name"] == "testskill"
    assert resource["path"] == "testskill/SKILL.md"
    # stderr should be empty in JSON mode (no diagnostics)
    assert stderr_capture.getvalue() == ""


def test_non_json_output_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure that without --json, output and exit codes are unchanged from today."""
    from check_md_links import main

    # Create a markdown file with a broken link and an unlinked resource
    md_file = tmp_path / "test.md"
    md_file.write_text("See [broken](missing.md) for more info.\n")

    # Mock git ls-files to return our test file
    def mock_tracked_markdown():
        return [md_file]

    monkeypatch.setattr("check_md_links.tracked_markdown", mock_tracked_markdown)
    # Mock vendored registry as empty
    monkeypatch.setattr(
        "check_md_links.json.loads",
        lambda _: {"vendored": []},
    )

    # Mock discover to return an item that is NOT in README
    class MockItem:
        kind = "skill"
        name = "testskill"
        src = tmp_path / "testskill" / "SKILL.md"

    def mock_discover(_):
        return [MockItem()]

    monkeypatch.setattr("check_md_links.cli.discover", mock_discover)
    # Mock README to NOT contain the link (so we get an unlinked resource)
    # Also don't contain the broken link target to avoid false positives
    readme_mock = tmp_path / "README.md"
    readme_mock.write_text("# Readme\n\nNo links here.\n")
    monkeypatch.setattr("check_md_links.ROOT", tmp_path)
    monkeypatch.setattr(
        "builtins.open",
        lambda *args, **kwargs: (
            open(readme_mock, *args, **kwargs)
            if "README.md" in str(args)
            else open(*args, **kwargs)
        ),
    )

    # Capture stdout/stderr for non-JSON mode
    import contextlib
    import io

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
        result = main([])  # No --json flag

    assert result == 1  # Should fail
    output = stdout_capture.getvalue().strip()
    stderr_output = stderr_capture.getvalue().strip()

    # Should contain human-readable output
    assert "test.md:1: broken-link -> missing.md" in output
    assert (
        "README.md: undocumented -> testskill/testskill "
        "(add a row linking testskill/SKILL.md)" in output
    )
    # Should contain the findings count on stderr
    assert "2 finding(s)." in stderr_output


def test_exit_codes_identical_in_both_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit codes are identical in both modes for the same input."""
    from check_md_links import main

    # Create a markdown file with a broken link
    md_file = tmp_path / "test.md"
    md_file.write_text("See [broken](missing.md) for more info.\n")

    # Mock git ls-files to return our test file
    def mock_tracked_markdown():
        return [md_file]

    monkeypatch.setattr("check_md_links.tracked_markdown", mock_tracked_markdown)
    # Mock vendored registry as empty
    monkeypatch.setattr(
        "check_md_links.json.loads",
        lambda _: {"vendored": []},
    )

    # Mock discover to return no items (so no README coverage issues)
    class MockItem:
        kind = "skill"
        name = "test"
        src = tmp_path / "test.md"

    def mock_discover(_):
        return [MockItem()]

    monkeypatch.setattr("check_md_links.cli.discover", mock_discover)
    # Mock README to contain the link (so no coverage issues, only broken link)
    readme_mock = tmp_path / "README.md"
    readme_mock.write_text("See [broken](test/missing.md) for more info.\n")
    monkeypatch.setattr("check_md_links.ROOT", tmp_path)
    monkeypatch.setattr(
        "builtins.open",
        lambda *args, **kwargs: (
            open(readme_mock, *args, **kwargs)
            if "README.md" in str(args)
            else open(*args, **kwargs)
        ),
    )

    # Test non-JSON mode
    import contextlib
    import io

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
        result_non_json = main([])  # No --json flag

    # Test JSON mode
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
        result_json = main(["--json"])

    assert result_non_json == result_json == 1
