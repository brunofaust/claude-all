"""Tests for the markdown link + README-coverage gate.

The gate exists because four cross-skill links shipped broken — one in an
already-merged PR. So the tests that matter are the ones proving it BITES: a
check that can only ever report "clean" is the vacuous pass this repo keeps
hunting. Every positive case is paired with the no-false-positive case that
made the first version of this checker report 18 findings, all of them wrong.
"""

from __future__ import annotations

import contextlib
import io
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


# Tests for JSON mode


def setup_git_repo(tmp_path: Path) -> Path:
    """Initialize a git repo in tmp_path and return the repo path."""
    repo_path = tmp_path
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True)
    return repo_path


def test_json_clean_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json on a clean tree should output JSON with pass: true and zero counts."""
    repo = setup_git_repo(tmp_path)
    # Create a simple markdown file with no links and a README that links a resource.
    (repo / "foo.md").write_text("# Foo\n")
    (repo / "README.md").write_text("# Readme\n")
    # Create a vendored.json with an empty vendored list.
    (repo / "vendored.json").write_text('{"vendored": []}')
    # We need to mock the ROOT and the discover function to avoid touching the real repo.
    # Instead, we'll change the current working directory and use relative imports.
    # But the script uses ROOT from the module globals. We'll monkeypatch the module's ROOT.
    import check_md_links

    monkeypatch.setattr(check_md_links, "ROOT", repo)
    # For discover, we need to mock it to return an empty list.
    monkeypatch.setattr(check_md_links, "discover", lambda _: [])
    # Run the script with --json.
    from check_md_links import main

    # We'll capture stdout and stderr.
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--json"])
    except SystemExit as e:
        result = e.code if isinstance(e.code, int) else 1
    # Parse the JSON output.
    data = json.loads(stdout.getvalue())
    assert data["pass"] is True
    assert data["markdown_files_scanned"] == 1  # foo.md
    assert data["links_resolved"] == 0
    assert data["resources_checked"] == 0
    assert data["files_skipped_as_vendored"] == 0
    assert data["broken_links"] == []
    assert data["unlinked_resources"] == []
    assert result == 0
    # Ensure no output to stderr.
    assert stderr.getvalue() == ""


def test_json_broken_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json with a broken link should output JSON with the broken link details."""
    repo = setup_git_repo(tmp_path)
    # Create a markdown file with a broken link.
    (repo / "foo.md").write_text("# Foo\nSee [broken](missing.md).\n")
    (repo / "README.md").write_text("# Readme\n")
    (repo / "vendored.json").write_text('{"vendored": []}')
    import check_md_links

    monkeypatch.setattr(check_md_links, "ROOT", repo)
    monkeypatch.setattr(check_md_links, "discover", lambda _: [])
    from check_md_links import main

    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--json"])
    except SystemExit as e:
        result = e.code if isinstance(e.code, int) else 1
    data = json.loads(stdout.getvalue())
    assert data["pass"] is False
    assert data["markdown_files_scanned"] == 1
    assert data["links_resolved"] == 1
    assert data["resources_checked"] == 0
    assert data["files_skipped_as_vendored"] == 0
    assert len(data["broken_links"]) == 1
    link = data["broken_links"][0]
    assert link["file"] == "foo.md"
    assert link["line_no"] == 2
    assert link["link_target"] == "missing.md"
    # The resolved path should be the absolute path of the missing file.
    expected_path = (repo / "missing.md").resolve()
    assert link["resolved_path"] == str(expected_path)
    assert data["unlinked_resources"] == []
    assert result == 1
    # No output to stderr.
    assert stderr.getvalue() == ""


def test_json_unlinked_resource(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json with an unlinked resource should output JSON with the resource details."""
    repo = setup_git_repo(tmp_path)
    (repo / "foo.md").write_text("# Foo\n")
    # Create a resource (a skill directory with a SKILL.md) that is not linked in README.
    skill_dir = repo / "src" / "myskill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("name: myskill\n")
    (repo / "README.md").write_text("# Readme\n")  # No link to the skill.
    (repo / "vendored.json").write_text('{"vendored": []}')
    import check_md_links

    monkeypatch.setattr(check_md_links, "ROOT", repo)

    # We need to mock the discover function to return our skill.
    # We'll create a mock item.
    class Item:
        def __init__(self, kind, name, src):
            self.kind = kind
            self.name = name
            self.src = src

    def discover(_):
        return [Item("skill", "myskill", skill_dir)]

    monkeypatch.setattr(check_md_links, "discover", discover)
    from check_md_links import main

    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--json"])
    except SystemExit as e:
        result = e.code if isinstance(e.code, int) else 1
    data = json.loads(stdout.getvalue())
    assert data["pass"] is False
    assert data["markdown_files_scanned"] == 1  # foo.md
    assert data["links_resolved"] == 0
    assert data["resources_checked"] == 1
    assert data["files_skipped_as_vendored"] == 0
    assert data["broken_links"] == []
    assert len(data["unlinked_resources"]) == 1
    resource = data["unlinked_resources"][0]
    assert resource["path"] == "src/myskill/SKILL.md"
    assert resource["kind"] == "skill"
    assert resource["name"] == "myskill"
    assert result == 1
    assert stderr.getvalue() == ""


def test_json_default_output_unaffected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure that without --json, the output is the same as before."""
    repo = setup_git_repo(tmp_path)
    (repo / "foo.md").write_text("# Foo\nSee [broken](missing.md).\n")
    skill_dir = repo / "src" / "myskill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("name: myskill\n")
    (repo / "README.md").write_text("# Readme\n")
    (repo / "vendored.json").write_text('{"vendored": []}')
    import check_md_links

    monkeypatch.setattr(check_md_links, "ROOT", repo)

    def discover(_):
        class Item:
            def __init__(self, kind, name, src):
                self.kind = kind
                self.name = name
                self.src = src

        return [Item("skill", "myskill", skill_dir)]

    monkeypatch.setattr(check_md_links, "discover", discover)
    from check_md_links import main

    # Test without --json.
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main([])
    except SystemExit as e:
        result = e.code if isinstance(e.code, int) else 1
    out_without_json = stdout.getvalue()
    err_without_json = stderr.getvalue()
    # Test with --json to get the structured data.
    stdout_json = io.StringIO()
    stderr_json = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_json), contextlib.redirect_stderr(stderr_json):
            result_json = main(["--json"])
    except SystemExit as e:
        result_json = e.code if isinstance(e.code, int) else 1
    # The exit codes should be the same.
    assert result == result_json
    # Without --json, we expect two lines:
    # one for the broken link and one for the unlinked resource.
    # Note: the line might be split differently if there are newlines,
    # but we strip and split by newline.
    lines = out_without_json.strip().splitlines()
    assert len(lines) == 2
    # First line: broken link.
    assert lines[0] == "foo.md:2: broken-link -> missing.md"
    # Second line: unlinked resource.
    assert lines[1].startswith("README.md: undocumented -> skill/myskill ")
    assert lines[1].endswith("(add a row linking src/myskill/SKILL.md)")
    # Stderr should have the count line.
    assert err_without_json.strip() == "2 finding(s)."
    # With --json, we should get valid JSON and no stdout besides JSON.
    data = json.loads(stdout_json.getvalue())
    assert data["pass"] is False
    assert len(data["broken_links"]) == 1
    assert len(data["unlinked_resources"]) == 1
    assert stderr_json.getvalue() == ""
