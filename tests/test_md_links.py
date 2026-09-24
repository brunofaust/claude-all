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


def test_json_output_has_expected_keys(monkeypatch, capsys):
    """JSON mode emits a valid object with the documented shape."""
    import importlib
    import json
    import sys

    monkeypatch.setattr(sys, "argv", ["check_md_links.py", "--json"])
    import check_md_links

    importlib.reload(check_md_links)
    code = check_md_links.main()
    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, dict)
    assert "pass" in data
    assert isinstance(data["pass"], bool)
    assert "counts" in data
    counts = data["counts"]
    for key in (
        "markdown_files_scanned",
        "links_resolved",
        "resources_checked",
        "files_skipped_as_vendored",
    ):
        assert key in counts
        assert isinstance(counts[key], int)
    assert "broken_links" in data
    assert isinstance(data["broken_links"], list)
    assert "unlinked_resources" in data
    assert isinstance(data["unlinked_resources"], list)
    assert code in (0, 1)


def test_json_output_is_only_json(monkeypatch, capsys):
    """--json produces only JSON on stdout, no human findings."""
    import importlib
    import json
    import sys

    monkeypatch.setattr(sys, "argv", ["check_md_links.py", "--json"])
    import check_md_links

    importlib.reload(check_md_links)
    check_md_links.main()
    out = capsys.readouterr().out
    # Should be parseable JSON and nothing else
    data = json.loads(out.strip())
    # Human messages must not appear
    assert "broken-link ->" not in out
    assert "README.md: undocumented" not in out
    # Ensure stdout is exactly JSON
    assert out.strip() == json.dumps(data)


def test_default_output_is_human_readable(monkeypatch, capsys):
    """Without --json, output remains human readable and not JSON."""
    import importlib
    import sys

    monkeypatch.setattr(sys, "argv", ["check_md_links.py"])
    import check_md_links

    importlib.reload(check_md_links)
    check_md_links.main()
    out = capsys.readouterr().out
    # Human output should not be a JSON object starting with {
    stripped = out.lstrip()
    assert not stripped.startswith("{"), "Default mode emitted JSON"
    # Exit code is tested implicitly by main returning int


def test_json_with_broken_link(monkeypatch, tmp_path):
    """--json reports a broken link with file/target/resolved_path."""
    from pathlib import Path

    import check_md_links

    # Create a real markdown file under ROOT so relative_to works
    root = Path(check_md_links.ROOT)
    test_dir = root / ".tmp_test_md_links"
    test_dir.mkdir(exist_ok=True)
    md_path = test_dir / "broken.md"
    md_path.write_text("[link](nonexistent_target.md)")
    try:
        # Force tracked_markdown to return only our file
        monkeypatch.setattr(check_md_links, "tracked_markdown", lambda: [md_path])
        # Ensure no vendored exemption
        report = check_md_links._collect_report([])
        # Should have scanned one file and one link checked
        assert report["counts"]["markdown_files_scanned"] == 1
        assert report["counts"]["links_resolved"] == 1
        assert report["pass"] is False
        assert len(report["broken_links"]) == 1
        bl = report["broken_links"][0]
        assert bl["file"] == md_path.relative_to(root).as_posix()
        assert bl["target"] == "nonexistent_target.md"
        # resolved_path should be relative to ROOT and point to missing file
        assert bl["resolved_path"].endswith("nonexistent_target.md")
    finally:
        # Cleanup
        try:
            md_path.unlink()
            test_dir.rmdir()
        except Exception:
            pass


def test_json_with_unlinked_resource(monkeypatch):
    """--json reports an unlinked resource when README lacks a link."""
    from pathlib import Path

    import check_md_links

    # Create a dummy resource path
    root = Path(check_md_links.ROOT)
    dummy_src = root / "src" / "claude_all" / "dummy_resource.md"

    # Ensure discover returns one item pointing to dummy_src
    class DummyItem:
        kind = "skill"
        name = "dummy"
        src = dummy_src

    # Monkeypatch discover to return our dummy
    import claude_all.cli as cli

    monkeypatch.setattr(cli, "discover", lambda _: [DummyItem()])
    # Monkeypatch README read to be empty so link is missing
    real_read_text = Path.read_text

    def fake_read_text(self):
        if self.name == "README.md":
            return ""
        return real_read_text(self)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    try:
        # No markdown files to scan
        monkeypatch.setattr(check_md_links, "tracked_markdown", lambda: [])
        report = check_md_links._collect_report([])
        assert report["counts"]["resources_checked"] == 1
        assert report["pass"] is False
        assert len(report["unlinked_resources"]) == 1
        assert report["unlinked_resources"][0] == dummy_src.relative_to(root).as_posix()
    finally:
        # Restore is handled by monkeypatch
        pass
