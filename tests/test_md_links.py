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
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_md_links import (
    CODE_SPAN,
    LINK,
    check_links,
    check_links_structured,
    check_readme_coverage_structured,
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


class TestCheckLinksStructured:
    def test_broken_link_returned(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Create a markdown file with a broken link
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            md_file = Path(tmp_dir) / "test.md"
            md_file.write_text("See [broken link](missing.md) for details.")
            # Make sure it's tracked by git (we'll monkeypatch tracked_markdown)
            monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
            # Empty vendored registry
            registry: list[dict] = []
            broken_links, files_scanned, links_resolved, files_skipped_vendored = (
                check_links_structured(registry)
            )
            assert files_scanned == 1
            assert links_resolved == 1
            assert files_skipped_vendored == 0
            assert len(broken_links) == 1
            bl = broken_links[0]
            assert bl["file"] == str(md_file.relative_to(ROOT))
            assert bl["target"] == "missing.md"
            # resolved_path should be the absolute path that was checked
            assert bl["resolved_path"] == str((md_file.parent / "missing.md").resolve())

    def test_vendored_file_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp_dir:
            md_file = Path(tmp_dir) / "vendored.md"
            md_file.write_text("Some link [here](http://example.com).")
            # Make it vendored
            registry = [{"path": str(md_file.parent.relative_to(ROOT)), "vendor_mode": "dir"}]
            monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
            broken_links, files_scanned, links_resolved, files_skipped_vendored = (
                check_links_structured(registry)
            )
            assert files_scanned == 0
            assert links_resolved == 0
            assert files_skipped_vendored == 1
            assert broken_links == []


class TestReadmeCoverageStructured:
    def test_unlinked_resource_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Mock cli.discover to return a fake resource
        class FakeResource:
            def __init__(self, src: Path, kind: str, name: str):
                self.src = src
                self.kind = kind
                self.name = name

        fake_src = Path("src/fake/skill/SKILL.md")
        fake_resource = FakeResource(fake_src, "skill", "fake")

        def fake_discover(_):
            return [fake_resource]

        monkeypatch.setattr("claude_all.cli.discover", fake_discover)
        # README does not contain the link
        readme_path = ROOT / "README.md"
        original_readme = readme_path.read_text()
        try:
            # Ensure the link is not present
            readme_path.write_text("# Readme\n")
            unlinked, resources_checked = check_readme_coverage_structured()
            assert resources_checked == 1
            assert len(unlinked) == 1
            assert unlinked[0]["path"] == str(fake_src)
        finally:
            readme_path.write_text(original_readme)


class TestJsonMode:
    def test_json_clean_tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Set up a temporary environment with no findings
        # We'll create a simple markdown file with no broken links
        md_file = tmp_path / "test.md"
        md_file.write_text(
            "See [working link](http://example.com) for details."
        )  # absolute URL, skipped
        # Monkeypatch tracked_markdown to return this file
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        # Empty vendored registry
        monkeypatch.setattr(
            "check_md_links.json.loads",
            lambda _: {"vendored": []},
        )
        # Mock cli.discover to return no resources
        monkeypatch.setattr("claude_all.cli.discover", lambda _: [])
        # Ensure README links the resource (but there are none, so it's vacuously true)
        # We'll temporarily replace the README with a minimal one
        readme_path = ROOT / "README.md"
        original_readme = readme_path.read_text()
        try:
            readme_path.write_text("# Readme\n")
            # Run the script with --json
            # We need to capture stdout and stderr
            import io
            import sys

            from check_md_links import main

            old_stdin = sys.stdin
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            stdin_capture = io.StringIO()
            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()
            sys.stdin = stdin_capture
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            try:
                # Simulate command line argument
                test_argv = ["check_md_links.py", "--json"]
                monkeypatch.setattr("sys.argv", test_argv)
                exit_code = main()
            finally:
                sys.stdin = old_stdin
                sys.stdout = old_stdout
                sys.stderr = old_stderr
            output = stdout_capture.getvalue()
            error_output = stderr_capture.getvalue()
            # Parse JSON
            data = json.loads(output)
            assert data["passed"] is True
            assert data["counts"]["markdown_files_scanned"] == 1
            assert (
                data["counts"]["links_resolved"] == 0
            )  # because the link was absolute and skipped
            assert data["counts"]["resources_checked"] == 0
            assert data["counts"]["files_skipped_as_vendored"] == 0
            assert data["broken_links"] == []
            assert data["unlinked_resources"] == []
            assert exit_code == 0
            # No output to stderr
            assert error_output == ""
        finally:
            readme_path.write_text(original_readme)

    def test_json_with_broken_link(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Create a markdown file with a broken relative link
        md_file = tmp_path / "test.md"
        md_file.write_text("See [broken link](missing.md) for details.")
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setattr(
            "check_md_links.json.loads",
            lambda _: {"vendored": []},
        )
        monkeypatch.setattr("claude_all.cli.discover", lambda _: [])
        readme_path = ROOT / "README.md"
        original_readme = readme_path.read_text()
        try:
            readme_path.write_text("# Readme\n")
            import io

            from check_md_links import main

            old_stdin = sys.stdin
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            stdin_capture = io.StringIO()
            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()
            sys.stdin = stdin_capture
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            try:
                test_argv = ["check_md_links.py", "--json"]
                monkeypatch.setattr("sys.argv", test_argv)
                exit_code = main()
            finally:
                sys.stdin = old_stdin
                sys.stdout = old_stdout
                sys.stderr = old_stderr
            output = stdout_capture.getvalue()
            error_output = stderr_capture.getvalue()
            data = json.loads(output)
            assert data["passed"] is False
            assert data["counts"]["markdown_files_scanned"] == 1
            assert data["counts"]["links_resolved"] == 1
            assert data["counts"]["resources_checked"] == 0
            assert data["counts"]["files_skipped_as_vendored"] == 0
            assert len(data["broken_links"]) == 1
            bl = data["broken_links"][0]
            assert bl["file"] == str(md_file.relative_to(ROOT))
            assert bl["target"] == "missing.md"
            assert bl["resolved_path"] == str((md_file.parent / "missing.md").resolve())
            assert data["unlinked_resources"] == []
            assert exit_code == 1
            # No stderr output in JSON mode
            assert error_output == ""
        finally:
            readme_path.write_text(original_readme)

    def test_json_with_unlinked_resource(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No markdown files to scan for links
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [])
        monkeypatch.setattr(
            "check_md_links.json.loads",
            lambda _: {"vendored": []},
        )

        # Mock cli.discover to return a fake resource
        class FakeResource:
            def __init__(self, src: Path, kind: str, name: str):
                self.src = src
                self.kind = kind
                self.name = name

        fake_src = Path("src/fake/skill/SKILL.md")
        fake_resource = FakeResource(fake_src, "skill", "fake")

        def fake_discover(_):
            return [fake_resource]

        monkeypatch.setattr("claude_all.cli.discover", fake_discover)
        readme_path = ROOT / "README.md"
        original_readme = readme_path.read_text()
        try:
            # Ensure the link is not present in README
            readme_path.write_text("# Readme\n")
            import io

            from check_md_links import main

            old_stdin = sys.stdin
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            stdin_capture = io.StringIO()
            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()
            sys.stdin = stdin_capture
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            try:
                test_argv = ["check_md_links.py", "--json"]
                monkeypatch.setattr("sys.argv", test_argv)
                exit_code = main()
            finally:
                sys.stdin = old_stdin
                sys.stdout = old_stdout
                sys.stderr = old_stderr
            output = stdout_capture.getvalue()
            error_output = stderr_capture.getvalue()
            data = json.loads(output)
            assert data["passed"] is False
            assert data["counts"]["markdown_files_scanned"] == 0
            assert data["counts"]["links_resolved"] == 0
            assert data["counts"]["resources_checked"] == 1
            assert data["counts"]["files_skipped_as_vendored"] == 0
            assert data["broken_links"] == []
            assert len(data["unlinked_resources"]) == 1
            assert data["unlinked_resources"][0]["path"] == str(fake_src)
            assert exit_code == 1
            assert error_output == ""
        finally:
            readme_path.write_text(original_readme)

    def test_non_json_output_unaffected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Ensure that without --json, the output and exit code are unchanged
        # We'll test with a broken link and compare the output to the expected human-readable format
        md_file = tmp_path / "test.md"
        md_file.write_text("See [broken link](missing.md) for details.")
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setattr(
            "check_md_links.json.loads",
            lambda _: {"vendored": []},
        )
        monkeypatch.setattr("claude_all.cli.discover", lambda _: [])
        readme_path = ROOT / "README.md"
        original_readme = readme_path.read_text()
        try:
            readme_path.write_text("# Readme\n")
            import io

            from check_md_links import main

            old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
            sys.stdin = io.StringIO()
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            output = ""
            error_output = ""
            try:
                test_argv = ["check_md_links.py"]  # no --json
                monkeypatch.setattr("sys.argv", test_argv)
                exit_code = main()
                output = sys.stdout.getvalue()
                error_output = sys.stderr.getvalue()
            finally:
                sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr
            # Expected human-readable output
            rel_path = md_file.relative_to(ROOT)
            expected_output = f"{rel_path}:1: broken-link -> missing.md\n"
            assert output == expected_output
            # Stderr should contain the count line
            assert "1 finding(s)." in error_output
            assert exit_code == 1
        finally:
            readme_path.write_text(original_readme)
