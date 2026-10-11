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
        broken_links, _, _, _ = check_links(registry=[])
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
    def _setup_git_repo(self, tmp_path: Path) -> Path:
        """Initialize a git repo in tmp_path and return the repo path."""
        repo = tmp_path
        (repo / ".git").mkdir()
        (repo / ".git" / "config").write_text("[core]\n")
        # Initialize an empty repo by running git init
        import subprocess

        subprocess.run(
            ["git", "init"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        # Set user info for commits
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo,
            check=True,
        )
        return repo

    def test_json_clean_tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """JSON mode on a clean tree should report pass: true and zero counts."""
        import json
        import subprocess

        repo = self._setup_git_repo(tmp_path)
        # Create a vendored.json with empty vendored list
        vendored: dict[str, list] = {"vendored": []}
        (repo / "vendored.json").write_text(json.dumps(vendored))
        # Create a README.md
        (repo / "README.md").write_text("# README\n")
        # Create a Markdown file with a valid link (to itself? but we'll avoid self-link)
        # Instead, we create a linked resource and link to it.
        # We'll create a dummy resource file and link to it from the README.
        # But for the link check, we need a Markdown file with a link that resolves.
        # Let's create a Markdown file with a link to a file that exists.
        md_file = repo / "test.md"
        md_file.write_text(
            "See [link](./test.md)\n"
        )  # self-link, but note: we strip anchor and check existence -> exists
        # However, note: the link is to itself, which exists -> not broken.
        # We also need to have the resource linked from README for the resource check.
        # We'll create a dummy resource and link to it in README.
        resource_file = repo / "resource.txt"
        resource_file.write_text("dummy")

        # We need to mock discover to return this resource.
        # We'll mock claude_all.cli.discover to return a list with a dummy item.
        class dummy_item:
            kind = "resource"
            name = "resource"
            src = resource_file

        monkeypatch.setattr("claude_all.cli.discover", lambda _: [dummy_item()])
        # Now, we need to set the tracked_markdown to return our markdown file.
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        # Also, we need to set the vendored.json path for the check_md_links module.
        # We'll monkeypatch the ROOT in check_md_links to be our repo.
        monkeypatch.setattr("check_md_links.ROOT", repo)
        # Run the script with --json and capture output
        result = subprocess.run(
            [sys.executable, "-m", "check_md_links", "--json"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["pass"] is True
        assert data["counts"]["markdown_files_scanned"] == 1
        assert data["counts"]["links_resolved"] == 1  # one link in the markdown file
        assert data["counts"]["resources_checked"] == 1
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert data["unlinked_resources"] == []

    def test_json_with_broken_link(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """JSON mode with a broken link should report pass: false and the broken link."""
        import json
        import subprocess

        repo = self._setup_git_repo(tmp_path)
        vendored: dict[str, list] = {"vendored": []}
        (repo / "vendored.json").write_text(json.dumps(vendored))
        (repo / "README.md").write_text("# README\n")
        # Create a Markdown file with a broken link
        md_file = repo / "test.md"
        md_file.write_text("See [link](./nonexistent.md)\n")
        # No resources to keep it simple
        monkeypatch.setattr("claude_all.cli.discover", lambda: [])
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setattr("check_md_links.ROOT", repo)
        result = subprocess.run(
            [sys.executable, "-m", "check_md_links", "--json"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1  # because there is a broken link
        data = json.loads(result.stdout)
        assert data["pass"] is False
        assert data["counts"]["markdown_files_scanned"] == 1
        assert data["counts"]["links_resolved"] == 1
        assert data["counts"]["resources_checked"] == 0
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert len(data["broken_links"]) == 1
        broken = data["broken_links"][0]
        assert broken["containing_file"] == "test.md"
        assert broken["raw_link_target"] == "./nonexistent.md"
        # resolved_path should be the absolute path to nonexistent.md
        assert broken["resolved_path"] == str((repo / "nonexistent.md").resolve())
        assert data["unlinked_resources"] == []

    def test_json_with_unlinked_resource(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """JSON mode with an unlinked resource should report pass: false and the resource."""
        import json
        import subprocess

        repo = self._setup_git_repo(tmp_path)
        vendored: dict[str, list] = {"vendored": []}
        (repo / "vendored.json").write_text(json.dumps(vendored))
        (repo / "README.md").write_text("# README\n")
        # Create a Markdown file with no links (to avoid link findings)
        md_file = repo / "test.md"
        md_file.write_text("No links here.\n")
        # Create a resource file
        resource_file = repo / "resource.txt"
        resource_file.write_text("dummy")

        # Mock discover to return this resource, but not link it in README
        class dummy_item:
            kind = "resource"
            name = "resource"
            src = resource_file

        monkeypatch.setattr("claude_all.cli.discover", lambda _: [dummy_item()])
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setattr("check_md_links.ROOT", repo)
        result = subprocess.run(
            [sys.executable, "-m", "check_md_links", "--json"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1  # because there is an unlinked resource
        data = json.loads(result.stdout)
        assert data["pass"] is False
        assert data["counts"]["markdown_files_scanned"] == 1
        assert data["counts"]["links_resolved"] == 0
        assert data["counts"]["resources_checked"] == 1
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert len(data["unlinked_resources"]) == 1
        assert data["unlinked_resources"][0] == "resource.txt"

    def test_json_default_output_unaffected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ensure that without --json, the output is unchanged from before."""
        import subprocess

        repo = self._setup_git_repo(tmp_path)
        vendored: dict[str, list] = {"vendored": []}
        (repo / "vendored.json").write_text(json.dumps(vendored))
        (repo / "README.md").write_text("# README\n")
        # Create a Markdown file with a broken link
        md_file = repo / "test.md"
        md_file.write_text("See [link](./nonexistent.md)\n")
        # No resources
        monkeypatch.setattr("claude_all.cli.discover", lambda: [])
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md_file])
        monkeypatch.setattr("check_md_links.ROOT", repo)
        # Run without --json
        result = subprocess.run(
            [sys.executable, "-m", "check_md_links"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        # Should output the finding to stdout and the count line to stderr
        assert result.returncode == 1
        assert "test.md:1: broken-link -> ./nonexistent.md" in result.stdout
        assert "1 finding(s)." in result.stderr
        # Now run with --json and check that the JSON output is valid and the stdout is only JSON
        result_json = subprocess.run(
            [sys.executable, "-m", "check_md_links", "--json"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert result_json.returncode == 1
        # stdout should be valid JSON
        try:
            data = json.loads(result_json.stdout)
        except json.JSONDecodeError:
            raise AssertionError("JSON output is not valid JSON") from None
        # stderr should be empty in JSON mode (we decided not to output the finding count line)
        assert result_json.stderr == ""
        # The JSON should indicate a failure and the broken link
        assert data["pass"] is False
        assert len(data["broken_links"]) == 1
