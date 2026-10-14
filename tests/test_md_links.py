"""Tests for the markdown link + README-coverage gate."""

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
    return LINK.findall(CODE_SPAN.sub("", line))


class TestLinkExtraction:
    def test_plain_link_is_found(self) -> None:
        assert targets("see [the audit](references/audit.md) first") == ["references/audit.md"]

    def test_code_labelled_link_keeps_its_target(self) -> None:
        assert targets("| [`code-quality`](src/a/b.md) | x |") == ["src/a/b.md"]

    def test_bold_labelled_link_keeps_its_target(self) -> None:
        assert targets("| [**frontend**](src/a/b.md) |") == ["src/a/b.md"]

    def test_inline_code_generic_is_not_a_link(self) -> None:
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
        missing = tmp_path / "GONE.md"
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [missing])
        findings, _ = check_links(registry=[])
        assert findings == []


def test_non_vendored_routes_use_discoverable_skill_names() -> None:
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
    registry = json.loads((ROOT / "vendored.json").read_text(encoding="utf-8"))["vendored"]
    missing = [
        f"{entry['id']}:{relative_path}"
        for entry in registry
        for relative_path in entry.get("local_only", [])
        if not (ROOT / entry["path"] / relative_path).exists()
    ]

    assert missing == []


def test_claude_hook_examples_use_timeout_seconds() -> None:
    timeout_field = re.compile(r'"timeout"\s*:\s*(\d+)')
    findings: list[str] = []
    for path in sorted((ROOT / "src" / "claude_all").rglob("*.md")):
        for value in timeout_field.findall(path.read_text(encoding="utf-8")):
            if int(value) > 600:
                findings.append(f"{path.relative_to(ROOT)}: timeout={value}")

    assert findings == []


class TestMainJsonOutput:
    def test_json_clean_tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        # Create a fake cli module for the import in check_readme_coverage
        fake_cli = tmp_path / "src" / "claude_all" / "cli.py"
        fake_cli.parent.mkdir(parents=True, exist_ok=True)
        fake_cli.write_text("def discover(_): return []\n")
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "test"], cwd=tmp_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        vendored: dict = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))
        (tmp_path / "README.md").write_text("# README\n")
        (tmp_path / "test.md").write_text("# Test\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True
        )
        import sys
        from io import StringIO

        from check_md_links import main

        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            old_argv = sys.argv
            sys.argv = ["check_md_links.py", "--json"]
            exit_code = main()
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.argv = old_argv
        data = json.loads(output)
        assert data["passed"] is True
        assert data["markdown_files_scanned"] == 1
        assert data["links_resolved"] == 0
        assert data["files_skipped_vendored"] == 0
        assert data["resources_checked"] == 0
        assert data["broken_links"] == []
        assert data["unlinked_resources"] == []
        assert exit_code == 0

    def test_json_with_broken_link(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        # Create a fake cli module for the import in check_readme_coverage
        fake_cli = tmp_path / "src" / "claude_all" / "cli.py"
        fake_cli.parent.mkdir(parents=True, exist_ok=True)
        fake_cli.write_text("def discover(_): return []\n")
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "test"], cwd=tmp_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        vendored: dict = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))
        (tmp_path / "README.md").write_text("# README\n")
        (tmp_path / "test.md").write_text("# Test\n\n[link](nonexistent.md)")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True
        )
        import sys
        from io import StringIO

        from check_md_links import main

        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            old_argv = sys.argv
            sys.argv = ["check_md_links.py", "--json"]
            exit_code = main()
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.argv = old_argv
        data = json.loads(output)
        assert data["passed"] is False
        assert data["markdown_files_scanned"] == 1
        assert data["links_resolved"] == 1
        assert data["files_skipped_vendored"] == 0
        assert data["resources_checked"] == 0
        assert len(data["broken_links"]) == 1
        broken = data["broken_links"][0]
        assert broken["file"] == "test.md"
        assert broken["line"] == 3
        assert broken["target"] == "nonexistent.md"
        assert broken["resolved_path"].endswith("nonexistent.md")
        assert data["unlinked_resources"] == []
        assert exit_code == 1

    def test_json_with_unlinked_resource(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        # Create a fake cli module for the import in check_readme_coverage
        fake_cli = tmp_path / "src" / "claude_all" / "cli.py"
        fake_cli.parent.mkdir(parents=True, exist_ok=True)
        fake_cli.write_text("def discover(_): return []\n")
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "test"], cwd=tmp_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        vendored: dict = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))
        (tmp_path / "README.md").write_text("# README\n")
        (tmp_path / "test.md").write_text("# Test\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True
        )
        from unittest.mock import patch

        class FakeItem:
            def __init__(self, kind: str, name: str, src: Path) -> None:
                self.kind = kind
                self.name = name
                self.src = src

        fake_item = FakeItem("skill", "test-skill", tmp_path / "src" / "test-skill" / "SKILL.md")
        with patch("claude_all.cli.discover", return_value=[fake_item]):
            import sys
            from io import StringIO

            from check_md_links import main

            old_stdout = sys.stdout
            sys.stdout = StringIO()
            try:
                old_argv = sys.argv
                sys.argv = ["check_md_links.py", "--json"]
                exit_code = main()
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout
                sys.argv = old_argv
        data = json.loads(output)
        assert data["passed"] is False
        assert data["markdown_files_scanned"] == 1
        assert data["links_resolved"] == 0
        assert data["files_skipped_vendored"] == 0
        assert data["resources_checked"] == 1
        assert data["broken_links"] == []
        assert len(data["unlinked_resources"]) == 1
        unlinked = data["unlinked_resources"][0]
        assert unlinked["path"] == "src/test-skill/SKILL.md"
        assert unlinked["kind"] == "skill"
        assert unlinked["name"] == "test-skill"
        assert exit_code == 1

    def test_default_output_unaffected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        # Create a fake cli module for the import in check_readme_coverage
        fake_cli = tmp_path / "src" / "claude_all" / "cli.py"
        fake_cli.parent.mkdir(parents=True, exist_ok=True)
        fake_cli.write_text("def discover(_): return []\n")
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "test"], cwd=tmp_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        vendored: dict = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))
        (tmp_path / "README.md").write_text("# README\n")
        (tmp_path / "test.md").write_text("# Test\n\n[link](nonexistent.md)")
        from unittest.mock import patch

        class FakeItem:
            def __init__(self, kind: str, name: str, src: Path) -> None:
                self.kind = kind
                self.name = name
                self.src = src

        fake_item = FakeItem("skill", "test-skill", tmp_path / "src" / "test-skill" / "SKILL.md")
        with patch("claude_all.cli.discover", return_value=[fake_item]):
            import sys
            from io import StringIO

            from check_md_links import main

            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = StringIO()
            sys.stderr = StringIO()
            try:
                old_argv = sys.argv
                sys.argv = ["check_md_links.py"]
                exit_code = main()
                stdout_output = sys.stdout.getvalue()
                stderr_output = sys.stderr.getvalue()
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr
                sys.argv = old_argv
        lines = stdout_output.strip().splitlines()
        assert len(lines) == 2
        assert lines[0] == "test.md:3: broken-link -> nonexistent.md"
        assert lines[1] == (
            "README.md: undocumented -> skill/test-skill "
            "(add a row linking src/test-skill/SKILL.md)"
        )
        assert stderr_output.strip() == "2 finding(s)."
        assert exit_code == 1
