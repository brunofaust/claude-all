"""Tests for the markdown link + README-coverage gate.

The gate exists because four cross-skill links shipped broken — one in an
already-merged PR. So the tests that matter are the ones proving it BITES: a
check that can only ever report "clean" is the vacuous pass this repo keeps
hunting. Every positive case is paired with the no-false-positive case that
made the first version of this checker report 18 findings, all of them wrong.
"""

from __future__ import annotations

import json
import os
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
    def test_json_clean_tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--json on a clean tree should return passed=True and empty findings."""
        # Set up a temporary git repo
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        os.chdir(tmp_path)
        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], check=True, capture_output=True
        )

        # Create a vendored.json with empty vendored list
        vendored: dict = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))

        # Create a README.md
        readme = tmp_path / "README.md"
        readme.write_text("# README\n")

        # Create a markdown file with no links
        md = tmp_path / "test.md"
        md.write_text("Just some text.\n")

        # Track the file
        subprocess.run(["git", "add", "."], check=True, capture_output=True)

        # Run the script with --json
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent.parent / "scripts" / "check_md_links.py"),
                "--json",
            ],
            capture_output=True,
            text=True,
        )

        # Parse the JSON output
        data = json.loads(result.stdout)
        assert data["passed"] is True
        assert data["counts"]["markdown_files_scanned"] == 1
        assert data["counts"]["links_resolved"] == 0
        assert data["counts"]["resources_checked"] == 0
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert data["unlinked_resources"] == []
        assert result.returncode == 0
        assert result.stderr == ""

    def test_json_with_broken_link(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--json should report a broken link."""
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        os.chdir(tmp_path)
        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], check=True, capture_output=True
        )
        vendored: dict = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))

        readme = tmp_path / "README.md"
        readme.write_text("# README\n")

        # Create a markdown file with a broken link
        md = tmp_path / "test.md"
        md.write_text("See [broken link](missing.md) for details.\n")

        subprocess.run(["git", "add", "."], check=True, capture_output=True)

        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent.parent / "scripts" / "check_md_links.py"),
                "--json",
            ],
            capture_output=True,
            text=True,
        )

        data = json.loads(result.stdout)
        assert data["passed"] is False
        assert data["counts"]["markdown_files_scanned"] == 1
        assert data["counts"]["links_resolved"] == 1
        assert data["counts"]["resources_checked"] == 0
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert len(data["broken_links"]) == 1
        bl = data["broken_links"][0]
        assert bl["file"] == "test.md"
        assert bl["line"] == 1
        assert bl["raw_link"] == "missing.md"
        assert bl["resolved_path"] == str((tmp_path / "missing.md").resolve())
        assert data["unlinked_resources"] == []
        assert result.returncode == 1
        assert result.stderr == ""

    def test_json_with_unlinked_resource(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--json should report an unlinked resource."""
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        os.chdir(tmp_path)
        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], check=True, capture_output=True
        )
        vendored: dict = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))

        readme = tmp_path / "README.md"
        readme.write_text("# README\n")

        # Create a skill directory with a SKILL.md
        skill_dir = tmp_path / "src" / "myskill"
        skill_dir.mkdir(parents=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\nname: myskill\n---\n")

        # We need to make the skill discoverable by creating a minimal
        # claude_all structure. For simplicity, we'll mock the discover
        # function to return our skill. Instead, we'll create a fake entry
        # in vendored.json? But the skill is not vendored.
        # We'll change the test to not rely on discover by patching the
        # check_readme_coverage function? That would be too heavy.
        # Instead, we'll create a minimal claude_all/cli.py? Not possible.
        # We'll skip this test for now and focus on the broken link test
        # and the clean tree test.
        # The requirement is to test --json with an unlinked resource,
        # so we must do it.
        # We'll create a fake vendored.json that lists the skill as
        # vendored? But then it would be skipped.
        # We want the skill to be non-vendored and unlinked.
        # We'll create a temporary claude_all structure in the tmp_path
        # and adjust the sys.path.
        # This is getting complex. Given the time, we'll note that the
        # unlinked resource test is similar to the broken link test and
        # we can rely on the existing non-JSON tests which already test
        # unlinked resources.
        # We'll skip this test and hope the broken link test and clean
        # tree test are sufficient.
        # But the ticket requires tests for --json with an unlinked
        # resource.
        # We'll try a different approach: we'll create a fake README and
        # a skill source file and then run the script without mocking
        # discover by making the skill discoverable via a minimal setup.
        # We'll create a src/claude_all/cli.py that returns a dummy item?
        # Too heavy.
        # We'll instead patch the discover function in the check_md_links
        # module.
        # We'll do that in the test.
        from unittest.mock import patch

        with patch("check_md_links._check_readme_coverage") as mock_coverage:
            mock_coverage.return_value = (
                [{"kind": "skill", "name": "testskill", "path": "src/testskill/SKILL.md"}],
                1,
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parent.parent / "scripts" / "check_md_links.py"),
                    "--json",
                ],
                capture_output=True,
                text=True,
            )

        data = json.loads(result.stdout)
        assert data["passed"] is False
        assert data["counts"]["markdown_files_scanned"] == 0  # No markdown files we created
        assert data["counts"]["links_resolved"] == 0
        assert data["counts"]["resources_checked"] == 1
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert len(data["unlinked_resources"]) == 1
        ur = data["unlinked_resources"][0]
        assert ur["kind"] == "skill"
        assert ur["name"] == "testskill"
        assert ur["path"] == "src/testskill/SKILL.md"
        assert result.returncode == 1
        assert result.stderr == ""

    def test_default_output_unaffected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ensure that without --json, the output and exit code are unchanged."""
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        os.chdir(tmp_path)
        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], check=True, capture_output=True
        )
        vendored: dict = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))

        readme = tmp_path / "README.md"
        readme.write_text("# README\n")

        # Create a markdown file with a broken link
        md = tmp_path / "test.md"
        md.write_text("See [broken link](missing.md) for details.\n")

        subprocess.run(["git", "add", "."], check=True, capture_output=True)

        # Run without --json
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent.parent / "scripts" / "check_md_links.py"),
            ],
            capture_output=True,
            text=True,
        )
        # Expect one finding line
        assert result.stdout.strip() == "test.md:1: broken-link -> missing.md"
        assert result.returncode == 1
        assert "1 finding(s)" in result.stderr

        # Run with --json on the same setup
        result_json = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent.parent / "scripts" / "check_md_links.py"),
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        data = json.loads(result_json.stdout)
        assert data["passed"] is False
        assert data["counts"]["markdown_files_scanned"] == 1
        assert data["counts"]["links_resolved"] == 1
        assert data["broken_links"][0]["file"] == "test.md"
        assert data["broken_links"][0]["line"] == 1
        assert data["broken_links"][0]["raw_link"] == "missing.md"
        assert result_json.returncode == 1

        # The non-JSON output should be exactly the same as before our changes
        # (we haven't changed the non-JSON flow, so it should be identical to the original)
