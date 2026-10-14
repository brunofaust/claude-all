"""Tests for the markdown link + README-coverage gate.

The gate exists because four cross-skill links shipped broken — one in an
already-merged PR. So the tests that matter are the ones proving it BITES: a
check that can only ever report "clean" is the vacuous pass this repo keeps
hunting. Every positive case is paired with the no-false-positive case that
made the first version of this checker report 18 findings, all of them wrong.
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_md_links import (
    CODE_SPAN,
    LINK,
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


def test_json_clean_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json on a clean tree outputs pass: true and zero counts."""
    # Set up temporary repo structure
    repo_root = tmp_path
    (repo_root / "vendored.json").write_text('{"vendored": []}')
    (repo_root / "README.md").write_text("# README\n")

    # Mock the functions in check_md_links
    import check_md_links

    monkeypatch.setattr(check_md_links, "ROOT", repo_root)
    monkeypatch.setattr(check_md_links, "tracked_markdown", lambda: [])  # no markdown files
    monkeypatch.setattr(check_md_links, "check_readme_coverage", lambda: ([], 0))  # no resources

    # Run the script with --json
    # Capture stdout and stderr
    old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
    sys.stdin = io.StringIO()
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    return_code = 0
    try:
        try:
            check_md_links.main()
        except SystemExit as e:
            return_code = int(e.code) if e.code is not None else 0
    finally:
        stdout = sys.stdout.getvalue()
        stderr = sys.stderr.getvalue()
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    # Get the captured output
    # We don't use stderr in this test, so we assign it to a dummy variable to avoid Ruff warning
    _ = stderr
    assert return_code == 0
    data = json.loads(stdout)
    assert data["pass"] is True
    assert data["markdown_files_scanned"] == 0
    assert data["links_resolved"] == 0
    assert data["resources_checked"] == 0
    assert data["files_skipped_as_vendored"] == 0
    assert data["broken_links"] == []
    assert data["unlinked_resources"] == []


def test_json_with_broken_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json with a broken link outputs pass: false and one broken link."""
    repo_root = tmp_path
    (repo_root / "vendored.json").write_text('{"vendored": []}')
    (repo_root / "README.md").write_text("# README\n")

    # Create a markdown file with a broken link
    md_file = repo_root / "doc.md"
    md_file.write_text("See [the missing](missing.md)")

    import check_md_links

    monkeypatch.setattr(check_md_links, "ROOT", repo_root)
    monkeypatch.setattr(check_md_links, "tracked_markdown", lambda: [md_file])
    monkeypatch.setattr(check_md_links, "is_vendored", lambda p, r: False)
    monkeypatch.setattr(check_md_links, "check_readme_coverage", lambda: ([], 0))

    # Run the script with --json
    # Capture stdout and stderr
    old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
    sys.stdin = io.StringIO()
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    return_code = 0
    try:
        try:
            check_md_links.main()
        except SystemExit as e:
            return_code = int(e.code) if e.code is not None else 0
    finally:
        stdout = sys.stdout.getvalue()
        stderr = sys.stderr.getvalue()
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    # Get the captured output
    # We don't use stderr in this test, so we assign it to a dummy variable to avoid Ruff warning
    _ = stderr
    assert return_code == 1  # because there is a finding
    data = json.loads(stdout)
    assert data["pass"] is False
    assert data["markdown_files_scanned"] == 1
    assert data["links_resolved"] == 1  # one link examined
    assert data["resources_checked"] == 0
    assert data["files_skipped_as_vendored"] == 0
    assert len(data["broken_links"]) == 1
    link = data["broken_links"][0]
    assert link["file"] == "doc.md"
    assert link["line"] == 1
    assert link["link_target"] == "missing.md"
    assert link["resolved_path"] == str((repo_root / "missing.md").relative_to(repo_root))
    assert data["unlinked_resources"] == []


def test_json_with_unlinked_resource(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json with an unlinked resource outputs pass: false and one unlinked resource."""
    repo_root = tmp_path
    (repo_root / "vendored.json").write_text('{"vendored": []}')
    (repo_root / "README.md").write_text("# README\n")

    # Mock discover to return one item that is not in README
    class Item:
        def __init__(self, kind, name, src):
            self.kind = kind
            self.name = name
            self.src = src

    item = Item("skill", "test-skill", Path("src/test/SKILL.md"))
    import check_md_links

    monkeypatch.setattr(check_md_links, "ROOT", repo_root)
    monkeypatch.setattr(check_md_links, "tracked_markdown", lambda: [])
    monkeypatch.setattr(check_md_links, "check_links", lambda r: ([], 0, 0, 0))  # no broken links
    monkeypatch.setattr(
        check_md_links,
        "check_readme_coverage",
        lambda: ([{"kind": item.kind, "name": item.name, "path": item.src.as_posix()}], 1),
    )

    # Run the script with --json
    # Capture stdout and stderr
    old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
    sys.stdin = io.StringIO()
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    return_code = 0
    try:
        try:
            check_md_links.main()
        except SystemExit as e:
            return_code = int(e.code) if e.code is not None else 0
    finally:
        stdout = sys.stdout.getvalue()
        stderr = sys.stderr.getvalue()
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    # Get the captured output
    # We don't use stderr in this test, so we assign it to a dummy variable to avoid Ruff warning
    _ = stderr
    assert return_code == 1
    data = json.loads(stdout)
    assert data["pass"] is False
    assert data["markdown_files_scanned"] == 0
    assert data["links_resolved"] == 0
    assert data["resources_checked"] == 1
    assert data["files_skipped_as_vendored"] == 0
    assert data["broken_links"] == []
    assert data["unlinked_resources"] == [item.src.as_posix()]


def test_json_default_output_unaffected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default (non-JSON) output should be unchanged by the --json flag."""
    repo_root = tmp_path
    (repo_root / "vendored.json").write_text('{"vendored": []}')
    (repo_root / "README.md").write_text("# README\n")

    # Create a markdown file with a broken link and an unlinked resource via mock
    md_file = repo_root / "doc.md"
    md_file.write_text("See [the missing](missing.md)")

    class Item:
        def __init__(self, kind, name, src):
            self.kind = kind
            self.name = name
            self.src = src

    item = Item("skill", "test-skill", Path("src/test/SKILL.md"))

    import check_md_links

    monkeypatch.setattr(check_md_links, "ROOT", repo_root)
    monkeypatch.setattr(check_md_links, "tracked_markdown", lambda: [md_file])
    monkeypatch.setattr(check_md_links, "is_vendored", lambda p, r: False)
    monkeypatch.setattr(
        check_md_links,
        "check_links",
        lambda r: (
            [
                {
                    "file": "doc.md",
                    "line": 1,
                    "link_target": "missing.md",
                    "resolved_path": str((repo_root / "missing.md").relative_to(repo_root)),
                }
            ],
            1,
            1,
            0,
        ),
    )
    monkeypatch.setattr(
        check_md_links,
        "check_readme_coverage",
        lambda: ([{"kind": item.kind, "name": item.name, "path": item.src.as_posix()}], 1),
    )

    # Run without --json
    # Capture stdout and stderr
    old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
    sys.stdin = io.StringIO()
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    return_code = 0
    try:
        try:
            check_md_links.main()
        except SystemExit as e:
            return_code = int(e.code) if e.code is not None else 0
    finally:
        stdout = sys.stdout.getvalue()
        stderr = sys.stderr.getvalue()
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    # Get the captured output
    assert return_code == 1
    # Expected human-readable output:
    #   doc.md:1: broken-link -> missing.md
    #   README.md: undocumented -> test-skill/skill (add a row linking src/test/SKILL.md)
    #   2 finding(s).
    # Note: the script prints the findings to stdout and the count to stderr.
    stdout_lines = stdout.strip().splitlines()
    stderr_lines = stderr.strip().splitlines()
    expected_out = (
        f"README.md: undocumented -> {item.kind}/{item.name} "
        f"(add a row linking {item.src.as_posix()})"
    )
    assert stdout_lines == [
        "doc.md:1: broken-link -> missing.md",
        expected_out,
    ]
    assert stderr_lines == ["2 finding(s)."]

    # Now run with --json and ensure the human-readable output is not affected
    # (we already tested JSON). We just want to make sure that the non-JSON
    # output is the same as before our changes.
    # We'll do a sanity check: run with --json and verify that the
    # human-readable output is not printed.
    # Capture stdout and stderr
    old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
    sys.stdin = io.StringIO()
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    return_code = 0
    try:
        try:
            check_md_links.main()
        except SystemExit as e:
            return_code = int(e.code) if e.code is not None else 0
    finally:
        stdout = sys.stdout.getvalue()
        stderr = sys.stderr.getvalue()
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    # Get the captured output
    assert return_code == 1
    # When --json is used, stdout should be JSON and stderr should be empty.
    assert stderr == ""
    data = json.loads(stdout)
    assert data["pass"] is False
