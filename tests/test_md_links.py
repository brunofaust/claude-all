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
from io import StringIO
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
    """A coherent vendor bundle can be pinned to an exact upstream commit.

    Args:
        tmp_path: Isolated clone destination.
        monkeypatch: Pytest fixture for replacing git execution.
    """
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
    def test_dir_mode_exempts_whole_tree(self) -> None:
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
        # `git ls-files` lists a tracked file even after it's deleted from the
        # working tree but not yet re-staged — check_links() must skip it instead
        # of crashing on read_text(). Regression for the CHANGELOG.md removal,
        # which crashed exactly this way.
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


# Tests for --json flag
def test_json_clean_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json on a clean tree should output JSON with pass:true and zero counts."""
    # Initialize a git repo
    monkeypatch.setattr("check_md_links.ROOT", tmp_path)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True)
    # Create a minimal vendored.json
    vendored: dict[str, list[dict]] = {"vendored": []}
    (tmp_path / "vendored.json").write_text(json.dumps(vendored))
    # Create a README.md to avoid errors in check_readme_coverage
    (tmp_path / "README.md").write_text("# README\n")
    # No markdown files tracked
    # Run main with --json
    from check_md_links import main

    # Capture stdout and stderr using StringIO
    stdout_capture = StringIO()
    stderr_capture = StringIO()

    # We need to monkey-patch the ROOT in check_md_links module
    import check_md_links

    check_md_links.ROOT = tmp_path

    # Redirect stdout and stderr
    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture
        exit_code = main()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    # Get the output
    output = stdout_capture.getvalue()
    err = stderr_capture.getvalue()

    # Parse JSON
    data = json.loads(output)
    assert data["pass"] is True
    assert data["counts"]["markdown_files_scanned"] == 0
    assert data["counts"]["links_resolved"] == 0
    assert data["counts"]["resources_checked"] == 0
    assert data["counts"]["files_skipped_as_vendored"] == 0
    assert data["broken_links"] == []
    assert data["unlinked_resources"] == []
    assert exit_code == 0
    # stderr should be empty (no diagnostics)
    assert err == ""


def test_json_broken_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json with a broken link should output JSON with pass:false and one broken link."""
    monkeypatch.setattr("check_md_links.ROOT", tmp_path)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True)
    # Create a markdown file with a broken link
    md = tmp_path / "doc.md"
    md.write_text("See [link](missing.md) for details.\n")
    subprocess.run(["git", "add", "doc.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "add doc"], cwd=tmp_path, check=True)
    # Vendored.json
    vendored: dict[str, list[dict]] = {"vendored": []}
    (tmp_path / "vendored.json").write_text(json.dumps(vendored))
    # README.md
    (tmp_path / "README.md").write_text("# README\n")
    # Run main with --json
    import check_md_links
    from check_md_links import main

    check_md_links.ROOT = tmp_path

    # Capture stdout and stderr using StringIO
    stdout_capture = StringIO()
    stderr_capture = StringIO()

    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture
        exit_code = main()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    stdout_val = stdout_capture.getvalue()
    stderr_val = stderr_capture.getvalue()

    # Parse JSON
    data = json.loads(stdout_val)
    assert data["pass"] is False
    assert data["counts"]["markdown_files_scanned"] == 1
    assert data["counts"]["links_resolved"] == 1
    assert data["counts"]["resources_checked"] == 0
    assert data["counts"]["files_skipped_as_vendored"] == 0
    assert len(data["broken_links"]) == 1
    bl = data["broken_links"][0]
    assert bl["file"] == "doc.md"
    assert bl["target"] == "missing.md"
    # resolved_path should be absolute path to tmp_path/doc.md's parent / missing.md resolved
    expected_resolved = (tmp_path / "missing.md").resolve()
    assert bl["resolved_path"] == str(expected_resolved)
    assert data["unlinked_resources"] == []
    assert exit_code == 1
    # stderr should be empty
    assert stderr_val == ""


def test_json_unlinked_resource(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json with an unlinked resource should output JSON with pass:false and one unlinked resource."""
    monkeypatch.setattr("check_md_links.ROOT", tmp_path)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True)
    # Create a markdown file (no links)
    md = tmp_path / "doc.md"
    md.write_text("# Doc\n")
    subprocess.run(["git", "add", "doc.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "add doc"], cwd=tmp_path, check=True)
    # Vendored.json
    vendored: dict[str, list[dict]] = {"vendored": []}
    (tmp_path / "vendored.json").write_text(json.dumps(vendored))
    # Create a skill directory and SKILL.md (to be discovered)
    skill_dir = tmp_path / "src" / "myskill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: myskill\n---\n# Skill\n")
    # We need to make sure the skill is discoverable by claude_all.cli.discover
    # For simplicity, we'll mock the discover function? But we don't want to depend on the actual discover.
    # Instead, we'll create a minimal claude_all structure? That's heavy.
    # Alternatively, we can patch the discover function in check_md_links to return a known item.
    # Let's do that.
    from types import SimpleNamespace
    from unittest.mock import patch

    # Create a mock item
    item = SimpleNamespace(kind="skill", name="myskill", src=skill_dir / "SKILL.md")

    # Patch claude_all.cli.discover to return [item]
    with patch("check_md_links.discover", return_value=[item]):
        (tmp_path / "README.md").write_text("# README\n")  # no link to the skill
        import check_md_links
        from check_md_links import main

        check_md_links.ROOT = tmp_path

        # Capture stdout and stderr using StringIO
        stdout_capture = StringIO()
        stderr_capture = StringIO()

        old_stdout, old_stderr = sys.stdout, sys.stderr
        try:
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            exit_code = main()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        stdout_val = stdout_capture.getvalue()
        stderr_val = stderr_capture.getvalue()

    data = json.loads(stdout_val)
    assert data["pass"] is False
    assert data["counts"]["markdown_files_scanned"] == 1
    assert data["counts"]["links_resolved"] == 0
    assert data["counts"]["resources_checked"] == 1
    assert data["counts"]["files_skipped_as_vendored"] == 0
    assert data["broken_links"] == []
    assert len(data["unlinked_resources"]) == 1
    # The unlinked resource path should be relative to ROOT
    assert data["unlinked_resources"][0] == "src/myskill/SKILL.md"
    assert exit_code == 1
    assert stderr_val == ""


def test_default_output_unaffected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure that without --json, the output and exit code are unchanged."""
    monkeypatch.setattr("check_md_links.ROOT", tmp_path)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True)
    # Create a markdown file with a broken link
    md = tmp_path / "doc.md"
    md.write_text("See [link](missing.md) for details.\n")
    subprocess.run(["git", "add", "doc.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "add doc"], cwd=tmp_path, check=True)
    # Vendored.json
    vendored: dict[str, list[dict]] = {"vendored": []}
    (tmp_path / "vendored.json").write_text(json.dumps(vendored))
    # README.md
    (tmp_path / "README.md").write_text("# README\n")
    # Test without --json
    import check_md_links
    from check_md_links import main

    check_md_links.ROOT = tmp_path

    # Capture stdout and stderr using StringIO
    stdout_capture_nojson = StringIO()
    stderr_capture_nojson = StringIO()

    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout = stdout_capture_nojson
        sys.stderr = stderr_capture_nojson
        exit_code_nojson = main()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    out_nojson = stdout_capture_nojson.getvalue()
    err_nojson = stderr_capture_nojson.getvalue()

    # Test with --json
    stdout_capture_json = StringIO()
    stderr_capture_json = StringIO()

    try:
        sys.stdout = stdout_capture_json
        sys.stderr = stderr_capture_json
        exit_code_json = main()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    out_json = stdout_capture_json.getvalue()
    err_json = stderr_capture_json.getvalue()

    # The JSON output should be valid JSON and contain the finding
    data = json.loads(out_json)
    assert data["pass"] is False
    assert len(data["broken_links"]) == 1
    # The non-JSON output should have the finding string
    assert out_nojson.strip() == "doc.md:1: broken-link -> missing.md"
    # The stderr should have the count line in non-JSON mode
    assert err_nojson.strip() == "1 finding(s)."
    # In JSON mode, stderr should be empty
    assert err_json == ""
    # Exit codes should be the same
    assert exit_code_nojson == exit_code_json == 1
