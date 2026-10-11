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
    """--json emits valid JSON with pass=True on a clean tree."""
    # Set up a temporary git repo with clean markdown files
    monkeypatch.setenv("HOME", str(tmp_path))
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()

    # Create a simple markdown file with no broken links
    md_file = repo_dir / "test.md"
    md_file.write_text("See [link](other.md) and [another](https://example.com)\n")

    # Create the target file
    (repo_dir / "other.md").write_text("# Test\n")

    # Create a minimal README that links the resource
    readme = repo_dir / "README.md"
    readme.write_text("See [test](test.md)\n")

    # Create minimal vendored.json
    vendored = repo_dir / "vendored.json"
    vendored.write_text('{"vendored": []}\n')

    # Change to repo directory and mock the paths
    monkeypatch.chdir(repo_dir)

    # Mock the discover function to return no items (so no resources to check)
    class MockItem:
        def __init__(self, kind, name, src):
            self.kind = kind
            self.name = name
            self.src = src

    def mock_discover(_):
        return []

    monkeypatch.setattr("check_md_links.discover", mock_discover)

    # Import and run the script with --json
    import sys

    sys.path.insert(0, str(repo_dir))
    import contextlib

    # Capture stdout/stderr
    from io import StringIO

    from check_md_links import main

    stdout = StringIO()
    stderr = StringIO()

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = main(["--json"])

    # Should return 0 (success)
    assert result == 0

    # Parse JSON output
    output = stdout.getvalue().strip()
    assert output.startswith("{") and output.endswith("}")
    data = json.loads(output)

    # Check structure
    assert "pass" in data
    assert "counts" in data
    assert "broken_links" in data
    assert "unlinked_resources" in data

    # Check values for clean tree
    assert data["pass"] is True
    assert data["counts"]["markdown_files_scanned"] >= 1  # test.md and README.md
    assert data["counts"]["links_resolved"] >= 1  # the [link](other.md) link
    assert data["counts"]["resources_checked"] == 0  # mocked discover returns empty
    assert data["counts"]["files_skipped_as_vendored"] == 0
    assert data["broken_links"] == []
    assert data["unlinked_resources"] == []


def test_json_output_with_broken_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json emits valid JSON with broken link details."""
    # Set up a temporary git repo
    monkeypatch.setenv("HOME", str(tmp_path))
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()

    # Create a markdown file with a broken link
    md_file = repo_dir / "test.md"
    md_file.write_text("See [broken](missing.md)\n")

    # Create a minimal README
    readme = repo_dir / "README.md"
    readme.write_text("# Test\n")

    # Create minimal vendored.json
    vendored = repo_dir / "vendored.json"
    vendored.write_text('{"vendored": []}\n')

    # Change to repo directory and mock the paths
    monkeypatch.chdir(repo_dir)

    # Mock the discover function to return no items
    def mock_discover(_):
        return []

    monkeypatch.setattr("check_md_links.discover", mock_discover)

    # Import and run the script with --json
    import sys

    sys.path.insert(0, str(repo_dir))
    import contextlib

    # Capture stdout/stderr
    from io import StringIO

    from check_md_links import main

    stdout = StringIO()
    stderr = StringIO()

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = main(["--json"])

    # Should return 1 (failure due to broken link)
    assert result == 1

    # Parse JSON output
    output = stdout.getvalue().strip()
    assert output.startswith("{") and output.endswith("}")
    data = json.loads(output)

    # Check structure
    assert data["pass"] is False
    assert data["counts"]["markdown_files_scanned"] >= 1
    assert data["counts"]["links_resolved"] >= 1
    assert len(data["broken_links"]) == 1

    # Check broken link details
    broken = data["broken_links"][0]
    assert broken["file"] == "test.md"
    assert broken["line"] == 1
    assert broken["raw_target"] == "missing.md"
    assert "resolved_path" in broken
    assert data["unlinked_resources"] == []


def test_json_output_with_unlinked_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--json emits valid JSON with unlinked resource details."""
    # Set up a temporary git repo
    monkeypatch.setenv("HOME", str(tmp_path))
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()

    # Create a markdown file with no links
    md_file = repo_dir / "test.md"
    md_file.write_text("# Test\n")

    # Create a README that does NOT link the resource
    readme = repo_dir / "README.md"
    readme.write_text("# Test\n")

    # Create minimal vendored.json
    vendored = repo_dir / "vendored.json"
    vendored.write_text('{"vendored": []}\n')

    # Change to repo directory and mock the paths
    monkeypatch.chdir(repo_dir)

    # Mock the discover function to return one item that's not in README
    class MockItem:
        def __init__(self, kind, name, src):
            self.kind = kind
            self.name = name
            self.src = src

    def mock_discover(_):
        return [MockItem("skill", "test-skill", Path("src/test/simple"))]

    monkeypatch.setattr("check_md_links.discover", mock_discover)

    # Import and run the script with --json
    import sys

    sys.path.insert(0, str(repo_dir))
    import contextlib

    # Capture stdout/stderr
    from io import StringIO

    from check_md_links import main

    stdout = StringIO()
    stderr = StringIO()

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = main(["--json"])

    # Should return 1 (failure due to unlinked resource)
    assert result == 1

    # Parse JSON output
    output = stdout.getvalue().strip()
    assert output.startswith("{") and output.endswith("}")
    data = json.loads(output)

    # Check structure
    assert data["pass"] is False
    assert len(data["unlinked_resources"]) == 1
    assert data["unlinked_resources"][0]["path"] == "src/test/simple"
    assert data["broken_links"] == []


def test_default_output_unaffected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure default (non-JSON) output and exit codes are unchanged."""
    # Set up a temporary git repo with a broken link
    monkeypatch.setenv("HOME", str(tmp_path))
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()

    # Create a markdown file with a broken link
    md_file = repo_dir / "test.md"
    md_file.write_text("See [broken](missing.md)\n")

    # Create a minimal README
    readme = repo_dir / "README.md"
    readme.write_text("# Test\n")

    # Create minimal vendored.json
    vendored = repo_dir / "vendored.json"
    vendored.write_text('{"vendored": []}\n')

    # Change to repo directory and mock the paths
    monkeypatch.chdir(repo_dir)

    # Mock the discover function to return no items
    def mock_discover(_):
        return []

    monkeypatch.setattr("check_md_links.discover", mock_discover)

    # Import and run the script WITHOUT --json
    import sys

    sys.path.insert(0, str(repo_dir))
    import contextlib

    # Capture stdout/stderr
    from io import StringIO

    from check_md_links import main

    stdout = StringIO()
    stderr = StringIO()

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = main([])  # No --json flag

    # Should return 1 (failure)
    assert result == 1

    # Check human-readable output
    stdout_output = stdout.getvalue()
    stderr_output = stderr.getvalue()

    # Should contain the finding in stdout
    assert "test.md:1: broken-link -> missing.md" in stdout_output
    # Should contain the count in stderr
    assert "1 finding(s)." in stderr_output

    # Now run WITH --json and verify we get JSON instead
    stdout_json = StringIO()
    stderr_json = StringIO()

    with contextlib.redirect_stdout(stdout_json), contextlib.redirect_stderr(stderr_json):
        result_json = main(["--json"])

    # Should also return 1
    assert result_json == 1

    # Should be valid JSON, not human-readable text
    json_output = stdout_json.getvalue().strip()
    assert json_output.startswith("{") and json_output.endswith("}")
    data = json.loads(json_output)
    assert data["pass"] is False

    # stderr should be empty in JSON mode (diagnostics go to stderr but we have none)
    # Actually, in our implementation, we only print to stderr in non-JSON mode
    assert stderr_json.getvalue() == ""
