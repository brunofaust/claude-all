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


class TestJsonOutput:
    """Test the --json output mode."""

    def test_json_clean_tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--json on a clean tree should output passed: true and empty arrays."""
        # Set up a temporary git repo with no markdown links issues and all resources documented.
        monkeypatch.chdir(tmp_path)

        # Initialize git repo
        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], check=True, capture_output=True
        )

        # Create a vendored.json
        vendored: dict = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))

        # Create a README.md that documents a resource
        (tmp_path / "README.md").write_text("See [resource](resource/SKILL.md)")

        # Create a resource directory and SKILL.md
        resource_dir = tmp_path / "resource"
        resource_dir.mkdir()
        (resource_dir / "SKILL.md").write_text("# Resource\n")

        # Create a markdown file with a valid relative link
        (tmp_path / "doc.md").write_text("See [resource](resource/SKILL.md)")

        # Track the files with git
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], check=True, capture_output=True)

        # Monkeypatch the ROOT in the check_md_links module to be our tmp_path
        import check_md_links

        monkeypatch.setattr(check_md_links, "ROOT", tmp_path)

        # Monkeypatch the discover function to return our resource
        import claude_all.cli

        class Item:
            def __init__(self, kind, name, src):
                self.kind = kind
                self.name = name
                self.src = src

        def mock_discover(_):
            return [Item("skill", "resource", resource_dir / "SKILL.md")]

        monkeypatch.setattr(claude_all.cli, "discover", mock_discover)

        # Run the script with --json
        import contextlib
        import io

        from check_md_links import main

        # Save sys.argv and set it for the test
        old_argv = sys.argv
        try:
            sys.argv = [sys.argv[0], "--json"]
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = main()
        finally:
            sys.argv = old_argv

        # Parse the JSON output
        output = stdout.getvalue().strip()
        data = json.loads(output)

        # Assertions
        assert data["passed"] is True
        assert data["counts"]["markdown_files_scanned"] == 3  # README.md, doc.md, resource/SKILL.md
        assert data["counts"]["links_resolved"] == 2  # one in README.md, one in doc.md
        assert data["counts"]["resources_checked"] == 1  # one resource from discover
        assert data["counts"]["files_skipped_vendored"] == 0
        assert data["broken_links"] == []
        assert data["unlinked_resources"] == []
        assert result == 0  # exit code

        # Also ensure no output to stderr in JSON mode
        assert stderr.getvalue() == ""

    def test_json_with_broken_link(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--json with a broken link should output the broken link struct."""
        monkeypatch.chdir(tmp_path)

        # Initialize git repo
        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], check=True, capture_output=True
        )

        # Create a vendored.json
        vendored: dict = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))

        # Create a README.md (empty, no resources)
        (tmp_path / "README.md").write_text("# README\n")

        # Create a markdown file with a broken link
        (tmp_path / "doc.md").write_text("See [broken link](missing.md)")

        # Track the files with git
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], check=True, capture_output=True)

        # Monkeypatch the ROOT in the check_md_links module to be our tmp_path
        import check_md_links

        monkeypatch.setattr(check_md_links, "ROOT", tmp_path)

        # Monkeypatch the discover function to return an empty list (no resources)
        import claude_all.cli

        def mock_discover(_):
            return []

        monkeypatch.setattr(claude_all.cli, "discover", mock_discover)

        # Run the script with --json
        import contextlib
        import io

        from check_md_links import main

        # Save sys.argv and set it for the test
        old_argv = sys.argv
        try:
            sys.argv = [sys.argv[0], "--json"]
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = main()
        finally:
            sys.argv = old_argv

        output = stdout.getvalue().strip()
        data = json.loads(output)

        # Assertions
        assert data["passed"] is False
        assert data["counts"]["markdown_files_scanned"] == 2  # README.md and doc.md
        assert (
            data["counts"]["links_resolved"] == 1
        )  # the one link in doc.md (README.md has no links)
        assert data["counts"]["resources_checked"] == 0  # no resources discovered
        assert data["counts"]["files_skipped_vendored"] == 0
        assert len(data["broken_links"]) == 1
        broken_link = data["broken_links"][0]
        assert broken_link["file"] == "doc.md"
        assert broken_link["line"] == 1
        assert broken_link["target"] == "missing.md"
        # The resolved path should be absolute and not exist
        assert not Path(broken_link["resolved_path"]).exists()
        assert data["unlinked_resources"] == []
        assert result == 1  # exit code

        # Also test that non-JSON output is unchanged (we'll do in another test)

    def test_json_with_unlinked_resource(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--json with an unlinked resource should output the unlinked resource struct."""
        monkeypatch.chdir(tmp_path)

        # Initialize git repo
        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], check=True, capture_output=True
        )

        # Create a vendored.json
        vendored: dict = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))

        # Create a README.md that does NOT link to the resource
        (tmp_path / "README.md").write_text("# README\n")

        # Create a resource directory and SKILL.md
        resource_dir = tmp_path / "resource"
        resource_dir.mkdir()
        (resource_dir / "SKILL.md").write_text("# Resource\n")

        # Monkeypatch the discover function to return our resource (which is unlinked)
        import claude_all.cli

        class Item:
            def __init__(self, kind, name, src):
                self.kind = kind
                self.name = name
                self.src = src

        def mock_discover(_):
            return [Item("skill", "resource", resource_dir / "SKILL.md")]

        monkeypatch.setattr(claude_all.cli, "discover", mock_discover)

        # Monkeypatch the ROOT in the check_md_links module to be our tmp_path
        import check_md_links

        monkeypatch.setattr(check_md_links, "ROOT", tmp_path)

        # Create a markdown file (to have something scanned)
        (tmp_path / "doc.md").write_text("Hello")

        # Track the files with git
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], check=True, capture_output=True)

        # Run the script with --json
        import contextlib
        import io

        from check_md_links import main

        # Save sys.argv and set it for the test
        old_argv = sys.argv
        try:
            sys.argv = [sys.argv[0], "--json"]
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = main()
        finally:
            sys.argv = old_argv

        output = stdout.getvalue().strip()
        data = json.loads(output)

        # Assertions
        assert data["passed"] is False  # because we have an unlinked resource
        assert data["counts"]["markdown_files_scanned"] == 3  # README.md, doc.md, resource/SKILL.md
        assert data["counts"]["links_resolved"] == 0  # no links in any of the three
        assert data["counts"]["resources_checked"] == 1  # our testskill
        assert data["counts"]["files_skipped_vendored"] == 0
        assert data["broken_links"] == []
        assert len(data["unlinked_resources"]) == 1
        unlinked = data["unlinked_resources"][0]
        # The path should be relative to the tmp_path (which is the mocked ROOT)
        assert unlinked["path"] == "resource/SKILL.md"
        assert result == 1  # exit code

    def test_default_output_unaffected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ensure that without --json, the output and exit code are unchanged."""
        monkeypatch.chdir(tmp_path)

        # Initialize git repo
        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], check=True, capture_output=True
        )

        # Create a vendored.json
        vendored: dict = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))

        # Create a README.md
        (tmp_path / "README.md").write_text("# README\n")

        # Create a markdown file with a broken link
        (tmp_path / "doc.md").write_text("See [broken link](missing.md)")

        # Track the files with git
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], check=True, capture_output=True)

        # Monkeypatch the ROOT in the check_md_links module to be our tmp_path
        import check_md_links

        monkeypatch.setattr(check_md_links, "ROOT", tmp_path)

        # Monkeypatch the discover function to return an empty list (to avoid extra findings)
        import claude_all.cli

        def mock_discover(_):
            return []

        monkeypatch.setattr(claude_all.cli, "discover", mock_discover)

        # Test without --json
        import contextlib
        import io

        from check_md_links import main

        # Save sys.argv and set it for the test (no arguments)
        old_argv = sys.argv
        try:
            sys.argv = [sys.argv[0]]
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = main()
        finally:
            sys.argv = old_argv

        stdout_out = stdout.getvalue()
        stderr_out = stderr.getvalue()

        # Expected output: the broken link message and then the count message to stderr
        expected_stdout = "doc.md:1: broken-link -> missing.md\n"
        expected_stderr = "\n1 finding(s).\n"

        assert stdout_out == expected_stdout
        assert stderr_out == expected_stderr
        assert result == 1

        # Now test with --json on the same setup and ensure the JSON output corresponds
        import contextlib
        import io

        stdout_json = io.StringIO()
        stderr_json = io.StringIO()
        # Save sys.argv and set it for the test
        old_argv = sys.argv
        try:
            sys.argv = [sys.argv[0], "--json"]
            with contextlib.redirect_stdout(stdout_json), contextlib.redirect_stderr(stderr_json):
                result_json = main()
        finally:
            sys.argv = old_argv

        json_out = stdout_json.getvalue().strip()
        data = json.loads(json_out)

        assert data["passed"] is False
        assert len(data["broken_links"]) == 1
        assert data["unlinked_resources"] == []
        assert result_json == 1
        # In JSON mode, stderr should be empty
        assert stderr_json.getvalue() == ""
