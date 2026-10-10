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


class TestJsonOutput:
    def test_json_clean_tree(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """--json on a clean tree should emit JSON with pass: true and zero counts."""
        # Set up a temporary repository
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        # Create a vendored.json with empty vendored list
        vendored = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))
        # Create a README.md
        (tmp_path / "README.md").write_text("# README\n")
        # Create a markdown file with no links
        md = tmp_path / "test.md"
        md.write_text("Some text\n")
        # Mock tracked_markdown to return our markdown file
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md])
        # Mock discover to return no resources
        monkeypatch.setattr("check_md_links.discover", lambda _: [])

        # Import the main function from the script
        # Capture stdout and stderr
        import io
        import sys

        from check_md_links import main

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            # Run with --json
            exit_code = main(["--json"])
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        output = sys.stdout.getvalue().strip()
        err_output = sys.stderr.getvalue().strip()

        # Parse JSON
        data = json.loads(output)
        # Check shape
        assert data["pass"] is True
        assert data["counts"]["markdown_files_scanned"] == 1
        assert data["counts"]["links_resolved"] == 0
        assert data["counts"]["resources_checked"] == 0
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert data["unlinked_resources"] == []
        # No stderr output (diagnostics go to stderr, but there are none)
        assert err_output == ""
        # Exit code should be 0
        assert exit_code == 0

    def test_json_with_broken_link(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """--json with a broken link should emit JSON with pass: false and one broken link."""
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        vendored = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))
        (tmp_path / "README.md").write_text("# README\n")
        # Create a markdown file with a broken relative link
        md = tmp_path / "test.md"
        md.write_text("See [broken](nonexistent.md) for details.\n")
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md])
        monkeypatch.setattr("check_md_links.discover", lambda _: [])

        import io
        import sys

        from check_md_links import main

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            exit_code = main(["--json"])
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        output = sys.stdout.getvalue().strip()
        err_output = sys.stderr.getvalue().strip()

        data = json.loads(output)
        assert data["pass"] is False
        assert data["counts"]["markdown_files_scanned"] == 1
        assert data["counts"]["links_resolved"] == 1
        assert data["counts"]["resources_checked"] == 0
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert len(data["broken_links"]) == 1
        bl = data["broken_links"][0]
        assert bl["file"] == "test.md"
        assert bl["line"] == 1
        assert bl["raw_target"] == "nonexistent.md"
        # The resolved path should be the absolute path of nonexistent.md relative to tmp_path? We made it relative if possible.
        # Since we set ROOT to tmp_path, the resolved path should be relative to tmp_path.
        expected_resolved = (tmp_path / "nonexistent.md").resolve()
        try:
            expected_rel = expected_resolved.relative_to(tmp_path)
            expected_str = str(expected_rel)
        except ValueError:
            expected_str = str(expected_resolved)
        assert bl["resolved_path"] == expected_str
        assert data["unlinked_resources"] == []
        # Stderr should be empty (in JSON mode, we do not print findings count to stderr)
        assert err_output == ""
        # Exit code should be 1 (since there is a finding)
        assert exit_code == 1

    def test_json_with_unlinked_resource(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """--json with an unlinked resource should emit JSON with pass: false and one unlinked resource."""
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        vendored = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))
        # Create a README.md that does not link to the resource
        (tmp_path / "README.md").write_text("# README\n")
        # Create a resource directory with a SKILL.md
        resource_dir = tmp_path / "resources" / "testskill"
        resource_dir.mkdir(parents=True)
        skill_file = resource_dir / "SKILL.md"
        skill_file.write_text("# Test Skill\n")
        # We need to mock discover to return this resource.
        # We'll create a mock Item class that mimics the one from claude_all.cli
        from types import SimpleNamespace

        item = SimpleNamespace(kind="skill", name="testskill", src=skill_file)
        monkeypatch.setattr("check_md_links.discover", lambda _: [item])
        # No markdown files to scan for links
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [])

        import io
        import sys

        from check_md_links import main

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            exit_code = main(["--json"])
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        output = sys.stdout.getvalue().strip()
        err_output = sys.stderr.getvalue().strip()

        data = json.loads(output)
        assert data["pass"] is False
        assert data["counts"]["markdown_files_scanned"] == 0
        assert data["counts"]["links_resolved"] == 0
        assert data["counts"]["resources_checked"] == 1
        assert data["counts"]["files_skipped_as_vendored"] == 0
        assert data["broken_links"] == []
        assert len(data["unlinked_resources"]) == 1
        ur = data["unlinked_resources"][0]
        # The resource path should be relative to ROOT (tmp_path)
        expected_resource = skill_file.relative_to(tmp_path)
        assert ur["resource"] == str(expected_resource)
        # Stderr should be empty
        assert err_output == ""
        # Exit code should be 1
        assert exit_code == 1

    def test_non_json_output_unaffected(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """Ensure that without --json, the output and exit code are unchanged from today."""
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        vendored = {"vendored": []}
        (tmp_path / "vendored.json").write_text(json.dumps(vendored))
        (tmp_path / "README.md").write_text("# README\n")
        # Create a markdown file with a broken link and an unlinked resource scenario
        md = tmp_path / "test.md"
        md.write_text("See [broken](nonexistent.md) and []( SKIPPED due to empty anchor).\n")
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [md])
        # Create a resource that is not linked in README
        resource_dir = tmp_path / "resources" / "testskill"
        resource_dir.mkdir(parents=True)
        skill_file = resource_dir / "SKILL.md"
        skill_file.write_text("# Test Skill\n")
        from types import SimpleNamespace

        item = SimpleNamespace(kind="skill", name="testskill", src=skill_file)
        monkeypatch.setattr("check_md_links.discover", lambda _: [item])

        import io
        import sys

        from check_md_links import main

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            exit_code = main([])  # no --json
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        output = sys.stdout.getvalue().strip()
        err_output = sys.stderr.getvalue().strip()

        # Expect two findings: one broken link and one unlinked resource
        # The broken link line format: "test.md:1: broken-link -> nonexistent.md"
        # The unlinked resource line format: "README.md: undocumented -> resources/testskill/SKILL.md (add a row linking resources/testskill/SKILL.md)"
        lines = output.splitlines()
        assert len(lines) == 2
        assert lines[0] == "test.md:1: broken-link -> nonexistent.md"
        assert (
            lines[1]
            == "README.md: undocumented -> resources/testskill/SKILL.md (add a row linking resources/testskill/SKILL.md)"
        )
        # Stderr should have the count line
        assert err_output == "\n2 finding(s)."
        # Exit code should be 1
        assert exit_code == 1

        # Now test with a clean tree to ensure exit code 0 and no output
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [])
        monkeypatch.setattr("check_md_links.discover", lambda _: [])
        # Remove the markdown file we created? We'll just override the tracked_markdown to return empty.
        # Also, we need to ensure there are no markdown files. We'll not create any.
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            exit_code = main([])
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        output = sys.stdout.getvalue().strip()
        err_output = sys.stderr.getvalue().strip()
        assert output == ""
        assert err_output == ""
        assert exit_code == 0
