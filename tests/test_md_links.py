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

import check_md_links
from check_md_links import (
    CODE_SPAN,
    LINK,
    check_links,
    is_vendored,
    main,
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
        broken, counts = check_links(registry=[])
        assert broken == []
        assert counts["markdown_files_scanned"] == 0

    def test_vendored_file_is_counted_as_skipped_not_scanned(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The JSON counts must say how many files the vendored exemption skipped.
        upstream = ROOT / "src/x/skill/SKILL.md"
        registry = [{"path": "src/x/skill", "vendor_mode": "dir"}]
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [upstream])
        broken, counts = check_links(registry=registry)
        assert broken == []
        assert counts["vendored_files_skipped"] == 1
        assert counts["markdown_files_scanned"] == 0


def _clean_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the link scan at one file with a resolving link, and report no unlinked resources."""
    target = tmp_path / "target.md"
    target.write_text("ok\n")
    doc = tmp_path / "doc.md"
    doc.write_text("see [target](target.md)\n")
    monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [doc])
    monkeypatch.setattr("check_md_links.check_readme_coverage", lambda: ([], 2))


def _broken_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    doc = tmp_path / "doc.md"
    doc.write_text("intro\n\nsee [gone](missing.md)\n")
    monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [doc])
    monkeypatch.setattr("check_md_links.check_readme_coverage", lambda: ([], 2))
    return doc


def _unlinked_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("no links here\n")
    monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [doc])
    monkeypatch.setattr(
        "check_md_links.check_readme_coverage",
        lambda: (
            [
                {
                    "kind": "skill",
                    "name": "demo",
                    "path": "src/claude_all/skills/generic/demo/SKILL.md",
                }
            ],
            3,
        ),
    )


class TestJsonMode:
    def test_clean_tree_emits_passing_object(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _clean_tree(monkeypatch, tmp_path)
        assert main(["--json"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["pass"] is True
        assert report["broken_links"] == []
        assert report["unlinked_resources"] == []
        assert report["counts"]["markdown_files_scanned"] == 1
        assert report["counts"]["links_resolved"] == 1
        assert report["counts"]["resources_checked"] == 2

    def test_broken_link_is_reported_with_file_target_and_resolved_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        doc = _broken_tree(monkeypatch, tmp_path)
        assert main(["--json"]) == 1
        report = json.loads(capsys.readouterr().out)
        assert report["pass"] is False
        assert report["broken_links"] == [
            {
                "file": doc.as_posix(),
                "line": 3,
                "target": "missing.md",
                "resolved": (tmp_path / "missing.md").resolve().as_posix(),
            }
        ]

    def test_unlinked_resource_is_reported_with_kind_name_and_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _unlinked_tree(monkeypatch, tmp_path)
        assert main(["--json"]) == 1
        report = json.loads(capsys.readouterr().out)
        assert report["pass"] is False
        assert report["unlinked_resources"] == [
            {
                "kind": "skill",
                "name": "demo",
                "path": "src/claude_all/skills/generic/demo/SKILL.md",
            }
        ]

    def test_stdout_is_only_the_json_object(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _broken_tree(monkeypatch, tmp_path)
        main(["--json"])
        out = capsys.readouterr().out
        assert json.loads(out) is not None
        assert out.startswith("{") and out.endswith("}\n")

    def test_exit_codes_match_human_mode(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _broken_tree(monkeypatch, tmp_path)
        human = main([])
        capsys.readouterr()
        as_json = main(["--json"])
        capsys.readouterr()
        assert human == as_json == 1

        _clean_tree(monkeypatch, tmp_path)
        assert main([]) == main(["--json"]) == 0
        capsys.readouterr()


class TestHumanMode:
    def test_default_output_is_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        doc = _broken_tree(monkeypatch, tmp_path)
        assert main([]) == 1
        captured = capsys.readouterr()
        assert captured.out == f"{doc.as_posix()}:3: broken-link -> missing.md\n"
        assert captured.err == "\n1 finding(s).\n"

    def test_unlinked_line_is_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _unlinked_tree(monkeypatch, tmp_path)
        assert main([]) == 1
        assert capsys.readouterr().out == (
            "README.md: undocumented -> skill/demo "
            "(add a row linking src/claude_all/skills/generic/demo/SKILL.md)\n"
        )

    def test_clean_tree_prints_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _clean_tree(monkeypatch, tmp_path)
        assert main([]) == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


def test_real_repo_json_counts_are_non_vacuous(capsys: pytest.CaptureFixture[str]) -> None:
    """A gate that inspected nothing and passed would be a vacuous pass."""
    main(["--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["markdown_files_scanned"] > 0
    assert report["counts"]["resources_checked"] > 0
    assert report["counts"]["links_resolved"] > 0


def test_check_readme_coverage_reports_real_resources() -> None:
    unlinked, resources_checked = check_md_links.check_readme_coverage()
    assert resources_checked > 0
    assert all({"kind", "name", "path"} <= item.keys() for item in unlinked)


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
