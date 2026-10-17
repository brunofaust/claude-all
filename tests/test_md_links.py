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

import check_md_links as gate_module
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
        report = check_links(registry=[])
        assert report.broken == []
        assert report.scanned == 0


def _make_tree(tmp_path: Path, files: dict[str, str]) -> list[Path]:
    """Write a fake repo under tmp_path and return its markdown paths."""
    (tmp_path / "vendored.json").write_text('{"vendored": []}')
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return [tmp_path / name for name in files if name.endswith(".md")]


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """check_md_links pointed at a fake repo; README coverage is controlled per test."""
    monkeypatch.setattr(gate_module, "ROOT", tmp_path)
    monkeypatch.setattr(gate_module, "check_readme_coverage", lambda: ([], 0))
    return gate_module


class TestMainOutput:
    def test_json_clean_tree(
        self,
        gate,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mds = _make_tree(
            tmp_path,
            {"README.md": "[self](README.md)\n", "docs/a.md": "[ext](https://example.com)\n"},
        )
        monkeypatch.setattr(gate, "tracked_markdown", lambda: mds)
        monkeypatch.setattr(sys, "argv", ["check_md_links.py", "--json"])

        assert gate.main() == 0
        out = capsys.readouterr().out
        payload = json.loads(out)  # stdout must be exactly one JSON object
        assert payload["ok"] is True
        assert payload["error"] is None
        assert payload["broken_links"] == []
        assert payload["unlinked_resources"] == []
        assert payload["counts"]["markdown_scanned"] == 2
        assert payload["counts"]["links_checked"] == 1  # README.md only; URL skipped

    def test_json_broken_link(
        self,
        gate,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mds = _make_tree(tmp_path, {"src/a/b.md": "ok\n[x](../gone.md)\n"})
        monkeypatch.setattr(gate, "tracked_markdown", lambda: mds)
        monkeypatch.setattr(sys, "argv", ["check_md_links.py", "--json"])

        assert gate.main() == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False
        assert payload["broken_links"] == [
            {
                "file": "src/a/b.md",
                "line": 2,
                "target": "../gone.md",
                "resolved": "src/gone.md",
            }
        ]
        # A broken link is reported, not counted as a link that resolved.
        assert payload["counts"]["links_checked"] == 0
        assert payload["unlinked_resources"] == []

    def test_json_unlinked_resource(
        self,
        gate,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mds = _make_tree(tmp_path, {"README.md": "nothing linked\n"})
        monkeypatch.setattr(gate, "tracked_markdown", lambda: mds)
        unlinked = [gate.UnlinkedResource("skill", "my-skill", tmp_path / "src/x/SKILL.md")]
        monkeypatch.setattr(gate, "check_readme_coverage", lambda: (unlinked, 3))
        monkeypatch.setattr(sys, "argv", ["check_md_links.py", "--json"])

        assert gate.main() == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False
        assert payload["unlinked_resources"] == [
            {"kind": "skill", "name": "my-skill", "path": "src/x/SKILL.md"}
        ]
        assert payload["counts"]["resources_checked"] == 3

    def test_default_output_unchanged(
        self,
        gate,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mds = _make_tree(tmp_path, {"src/a/b.md": "[x](../gone.md)\n"})
        monkeypatch.setattr(gate, "tracked_markdown", lambda: mds)
        unlinked = [gate.UnlinkedResource("skill", "my-skill", tmp_path / "src/x/SKILL.md")]
        monkeypatch.setattr(gate, "check_readme_coverage", lambda: (unlinked, 3))
        monkeypatch.setattr(sys, "argv", ["check_md_links.py"])

        assert gate.main() == 1
        captured = capsys.readouterr()
        assert captured.out == (
            "src/a/b.md:1: broken-link -> ../gone.md\n"
            "README.md: undocumented -> skill/my-skill "
            "(add a row linking src/x/SKILL.md)\n"
        )
        assert captured.err == "\n2 finding(s).\n"

    def test_default_clean_tree_exits_zero_silently(
        self,
        gate,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mds = _make_tree(tmp_path, {"README.md": "clean\n"})
        monkeypatch.setattr(gate, "tracked_markdown", lambda: mds)
        monkeypatch.setattr(sys, "argv", ["check_md_links.py"])

        assert gate.main() == 0
        assert capsys.readouterr().out == ""

    def test_json_vendored_files_are_counted_not_scanned(
        self,
        gate,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mds = _make_tree(
            tmp_path,
            {"README.md": "clean\n", "vendor/x/SKILL.md": "[up](../../nowhere.md)\n"},
        )
        (tmp_path / "vendored.json").write_text(
            '{"vendored": [{"path": "vendor/x", "vendor_mode": "dir"}]}'
        )
        monkeypatch.setattr(gate, "tracked_markdown", lambda: mds)
        monkeypatch.setattr(sys, "argv", ["check_md_links.py", "--json"])

        assert gate.main() == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["broken_links"] == []
        assert payload["counts"]["vendored_skipped"] == 1
        assert payload["counts"]["markdown_scanned"] == 1
        assert payload["counts"]["links_checked"] == 0

    def test_json_internal_error_prints_error_object(
        self,
        gate,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _make_tree(tmp_path, {"README.md": "clean\n"})

        def boom() -> list[Path]:
            raise RuntimeError("boom")

        monkeypatch.setattr(gate, "tracked_markdown", boom)
        monkeypatch.setattr(sys, "argv", ["check_md_links.py", "--json"])

        assert gate.main() == 1
        captured = capsys.readouterr()
        assert json.loads(captured.out) == {"ok": False, "error": "RuntimeError: boom"}
        assert "check_md_links: RuntimeError: boom" in captured.err


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
