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
        findings, links_checked, broken_links = check_links(registry=[])
        assert findings == []
        assert links_checked == 0
        assert broken_links == []


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


class TestJsonMode:
    def test_json_clean_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """--json on a tree with no findings."""
        # Setup a temporary git repo with one markdown file and no links.
        # We'll mock the necessary functions to avoid touching the real repo.
        monkeypatch.setattr(
            "check_md_links.tracked_markdown",
            lambda: [tmp_path / "doc.md"],
        )
        monkeypatch.setattr(
            "check_md_links.is_vendored",
            lambda path, registry: False,
        )
        (tmp_path / "doc.md").write_text("# Hello\n")
        # Mock vendored.json to be empty
        monkeypatch.setattr(
            "check_md_links.Path.__add__",
            lambda self, other: (
                tmp_path / "vendored.json"
                if other == "vendored.json"
                else self.__class__.__add__(self, other)
            ),
        )
        # We'll monkeypatch the specific path used in main for vendored.json
        vendored_path = tmp_path / "vendored.json"
        vendored_path.write_text('{"vendored": []}')
        monkeypatch.setattr(
            "check_md_links.ROOT", tmp_path, raising=False
        )  # This is tricky; we'll instead mock the open call.
        # Better to mock the json.loads call? Let's instead set the ROOT in the module.
        # We'll do a more direct approach: monkeypatch the file read.
        original_open = Path.open

        def mock_open(self, *args, **kwargs):
            if self.name == "vendored.json":
                return open(vendored_path, *args, **kwargs)
            return original_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", mock_open)

        # Mock discover to return an empty list
        class MockItem:
            def __init__(self, kind, name, src):
                self.kind = kind
                self.name = name
                self.src = src

        monkeypatch.setattr(
            "check_md_links.discover",
            lambda _: [],
        )

        # Import main inside the test to get the mocked functions
        from check_md_links import main

        # Run with --json
        sys.argv = ["check_md_links.py", "--json"]
        # We need to change the current working directory to tmp_path for the git ls-files call?
        # But we mocked tracked_markdown, so it's fine.
        # Actually, we can just run and let the mocked functions handle it.
        # We'll change the working directory to tmp_path to avoid any real git calls.
        monkeypatch.setattr("os.chdir", lambda x: None)  # no-op
        monkeypatch.setattr(
            "builtins.__import__", lambda name, *args: __import__(name, *args)
        )  # no-op
        with monkeypatch.context() as m:
            m.setattr("os.getcwd", lambda: str(tmp_path))

            # We also need to mock subprocess.run for tracked_markdown,
            # but we already mocked tracked_markdown.
            # But tracked_markdown uses subprocess.run. We'll mock that too.
            def mock_run(*args, **kwargs):
                class MockResult:
                    stdout = "doc.md\0"
                    stderr = ""
                    returncode = 0

                return MockResult()

            m.setattr("subprocess.run", mock_run)
            exit_code = main()

        # Capture stdout and stderr
        captured = capsys.readouterr()
        # stdout should be JSON
        assert captured.out.strip()
        data = json.loads(captured.out)
        assert data["pass"] is True
        assert data["counts"]["markdown_files_scanned"] == 1
        assert data["counts"]["links_resolved"] == 0
        assert data["counts"]["resources_checked"] == 0
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert data["unlinked_resources"] == []
        assert exit_code == 0
        # stderr should be empty (no findings)
        assert captured.err == ""

    def test_json_with_broken_link(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """--json with a broken link."""
        # Setup a markdown file with a broken link.
        md_file = tmp_path / "doc.md"
        md_file.write_text("See [broken](missing.md)")

        # Mock tracked_markdown to return this file
        monkeypatch.setattr(
            "check_md_links.tracked_markdown",
            lambda: [md_file],
        )
        monkeypatch.setattr(
            "check_md_links.is_vendored",
            lambda path, registry: False,
        )
        # Mock vendored.json
        vendored_path = tmp_path / "vendored.json"
        vendored_path.write_text('{"vendored": []}')
        original_open = Path.open

        def mock_open(self, *args, **kwargs):
            if self.name == "vendored.json":
                return open(vendored_path, *args, **kwargs)
            return original_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", mock_open)

        # Mock discover to return empty
        monkeypatch.setattr(
            "check_md_links.discover",
            lambda _: [],
        )

        # Mock subprocess.run for tracked_markdown
        def mock_run(*args, **kwargs):
            class MockResult:
                stdout = f"{md_file.name}\0"
                stderr = ""
                returncode = 0

            return MockResult()

        monkeypatch.setattr("subprocess.run", mock_run)

        from check_md_links import main

        sys.argv = ["check_md_links.py", "--json"]
        with monkeypatch.context() as m:
            m.setattr("os.getcwd", lambda: str(tmp_path))
            exit_code = main()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["pass"] is False
        assert data["counts"]["markdown_files_scanned"] == 1
        assert data["counts"]["links_resolved"] == 1
        assert data["counts"]["resources_checked"] == 0
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert len(data["broken_links"]) == 1
        broken = data["broken_links"][0]
        assert broken["file"] == "doc.md"
        assert broken["line"] == 1
        assert broken["target"] == "missing.md"
        # resolved_path should be absolute path to tmp_path/doc.md's parent / missing.md
        expected_resolved = (tmp_path / "missing.md").resolve()
        assert broken["resolved_path"] == str(expected_resolved)
        assert data["unlinked_resources"] == []
        assert exit_code == 1
        # stderr should have the findings message
        assert "1 finding(s)." in captured.err

    def test_json_with_unlinked_resource(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """--json with an unlinked resource."""
        # We need a README and a resource discovered by discover that is not linked.
        readme = tmp_path / "README.md"
        readme.write_text("# README\n")

        # Mock discover to return one item
        class MockItem:
            def __init__(self, kind, name, src):
                self.kind = kind
                self.name = name
                self.src = src

        mock_item = MockItem("skill", "test-skill", tmp_path / "src" / "test-skill" / "SKILL.md")
        monkeypatch.setattr(
            "check_md_links.discover",
            lambda _: [mock_item],
        )
        # No markdown files to scan for links
        monkeypatch.setattr(
            "check_md_links.tracked_markdown",
            lambda: [],
        )
        # Mock vendored.json
        vendored_path = tmp_path / "vendored.json"
        vendored_path.write_text('{"vendored": []}')
        original_open = Path.open

        def mock_open(self, *args, **kwargs):
            if self.name == "vendored.json":
                return open(vendored_path, *args, **kwargs)
            return original_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", mock_open)

        from check_md_links import main

        sys.argv = ["check_md_links.py", "--json"]
        with monkeypatch.context() as m:
            m.setattr("os.getcwd", lambda: str(tmp_path))

            # Mock subprocess.run to return empty for tracked_markdown
            def mock_run(*args, **kwargs):
                class MockResult:
                    stdout = "\0"
                    stderr = ""
                    returncode = 0

                return MockResult()

            m.setattr("subprocess.run", mock_run)
            exit_code = main()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["pass"] is False
        assert data["counts"]["markdown_files_scanned"] == 0
        assert data["counts"]["links_resolved"] == 0
        assert data["counts"]["resources_checked"] == 1
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert len(data["unlinked_resources"]) == 1
        assert data["unlinked_resources"][0] == "src/test-skill/SKILL.md"
        assert exit_code == 1
        assert "1 finding(s)." in captured.err

    def test_non_json_output_unaffected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Ensure that without --json, the output is
        unchanged."""
        # We'll test with a broken link and compare the output
        # to the expected human-readable format.
        md_file = tmp_path / "doc.md"
        md_file.write_text("See [broken](missing.md)")
        readme = tmp_path / "README.md"
        readme.write_text("# README\n")

        # Mock tracked_markdown
        monkeypatch.setattr(
            "check_md_links.tracked_markdown",
            lambda: [md_file],
        )
        monkeypatch.setattr(
            "check_md_links.is_vendored",
            lambda path, registry: False,
        )
        # Mock vendored.json
        vendored_path = tmp_path / "vendored.json"
        vendored_path.write_text('{"vendored": []}')
        original_open = Path.open

        def mock_open(self, *args, **kwargs):
            if self.name == "vendored.json":
                return open(vendored_path, *args, **kwargs)
            return original_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", mock_open)

        # Mock discover to return empty (so no README findings)
        monkeypatch.setattr(
            "check_md_links.discover",
            lambda _: [],
        )

        # Mock subprocess.run for tracked_markdown
        def mock_run(*args, **kwargs):
            class MockResult:
                stdout = f"{md_file.name}\0"
                stderr = ""
                returncode = 0

            return MockResult()

        monkeypatch.setattr("subprocess.run", mock_run)

        from check_md_links import main

        # Run without --json
        sys.argv = ["check_md_links.py"]
        with monkeypatch.context() as m:
            m.setattr("os.getcwd", lambda: str(tmp_path))
            exit_code = main()

        captured = capsys.readouterr()
        # Expected output: one line for the broken link
        expected_out = "doc.md:1: broken-link -> missing.md\n"
        assert captured.out == expected_out
        # Expected stderr: the findings message
        assert captured.err.strip() == "1 finding(s)."
        assert exit_code == 1

        # Now run with --json and ensure the stdout is JSON and stderr still has the message
        sys.argv = ["check_md_links.py", "--json"]
        with monkeypatch.context() as m:
            m.setattr("os.getcwd", lambda: str(tmp_path))
            exit_code = main()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["pass"] is False
        assert data["counts"]["markdown_files_scanned"] == 1
        assert data["counts"]["links_resolved"] == 1
        assert data["counts"]["resources_checked"] == 0
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert len(data["broken_links"]) == 1
        # stderr should still have the findings message
        assert "1 finding(s)." in captured.err
        assert exit_code == 1
