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
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from check_md_links import (
    CODE_SPAN,
    LINK,
    check_links,
    check_readme_coverage,
    is_vendored,
    main,
    scan_links,
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


class TestCheckReadmeCoverage:
    def test_string_wrapper_keeps_the_human_line(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import claude_all.cli as cli

        src = ROOT / "src/claude_all/skills/generic/fake-skill/SKILL.md"
        fake = SimpleNamespace(kind="skills", name="fake-skill", src=src)
        monkeypatch.setattr(cli, "discover", lambda filters: [fake])

        assert check_readme_coverage() == [
            "README.md: undocumented -> skills/fake-skill "
            "(add a row linking src/claude_all/skills/generic/fake-skill/SKILL.md)"
        ]


class TestMainJson:
    """`--json` is the machine-readable contract; these pin its shape and exit codes."""

    def test_clean_tree_emits_one_passing_document(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--json"]) == 0
        out, err = capsys.readouterr()
        payload = json.loads(out)  # whole stdout must be one JSON document
        assert payload["schema_version"] == 1
        assert payload["passed"] is True
        assert payload["broken_links"] == []
        assert payload["unlinked_resources"] == []
        counts = payload["counts"]
        # Non-vacuous: the gate really inspected files, links and resources.
        assert counts["markdown_files_scanned"] > 0
        assert counts["links_checked"] > 0
        assert counts["links_resolved"] == counts["links_checked"]
        assert counts["resources_checked"] > 0
        assert err == ""

    def test_broken_link_is_reported_with_its_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        doc = tmp_path.resolve() / "doc.md"
        doc.write_text("intro\nsee [gone](missing/nope.md#sec)\n")
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [doc])

        assert main(["--json"]) == 1
        out, err = capsys.readouterr()
        payload = json.loads(out)
        assert payload["passed"] is False
        assert payload["broken_links"] == [
            {
                "file": doc.as_posix(),
                "line": 2,
                "target": "missing/nope.md#sec",
                "resolved_path": (doc.parent / "missing/nope.md").as_posix(),
            }
        ]
        assert payload["counts"]["links_checked"] == 1
        assert payload["counts"]["links_resolved"] == 0
        assert "finding(s)." in err

    def test_unlinked_resource_is_reported_with_its_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import claude_all.cli as cli

        src = ROOT / "src/claude_all/skills/generic/fake-skill/SKILL.md"
        fake = SimpleNamespace(kind="skills", name="fake-skill", src=src)
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [])
        monkeypatch.setattr(cli, "discover", lambda filters: [fake])

        assert main(["--json"]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["passed"] is False
        assert payload["unlinked_resources"] == [
            {
                "kind": "skills",
                "name": "fake-skill",
                "path": "src/claude_all/skills/generic/fake-skill/SKILL.md",
            }
        ]
        assert payload["counts"]["resources_checked"] == 1
        assert payload["broken_links"] == []


class TestMainDefaultOutput:
    def test_clean_tree_prints_nothing_on_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main([]) == 0
        out, err = capsys.readouterr()
        assert out == ""
        assert err == ""

    def test_broken_link_keeps_human_format(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        doc = tmp_path.resolve() / "doc.md"
        doc.write_text("see [gone](missing/nope.md#sec)\n")
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [doc])

        assert main([]) == 1
        out, err = capsys.readouterr()
        assert out == f"{doc}:1: broken-link -> missing/nope.md#sec\n"
        assert err == "\n1 finding(s).\n"

    def test_unlinked_resource_keeps_human_format(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import claude_all.cli as cli

        src = ROOT / "src/claude_all/skills/generic/fake-skill/SKILL.md"
        fake = SimpleNamespace(kind="skills", name="fake-skill", src=src)
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [])
        monkeypatch.setattr(cli, "discover", lambda filters: [fake])

        assert main([]) == 1
        out, err = capsys.readouterr()
        assert out == (
            "README.md: undocumented -> skills/fake-skill "
            "(add a row linking src/claude_all/skills/generic/fake-skill/SKILL.md)\n"
        )
        assert err == "\n1 finding(s).\n"


class TestExitCodeParity:
    def test_json_and_default_modes_exit_the_same_on_a_broken_link(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        doc = tmp_path.resolve() / "doc.md"
        doc.write_text("see [gone](missing/nope.md)\n")
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [doc])

        json_code = main(["--json"])
        capsys.readouterr()
        default_code = main([])
        capsys.readouterr()
        assert json_code == default_code == 1


class TestScanLinksCounts:
    def test_counts_follow_the_documented_definitions(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Anchors, external schemes and mailto are not counted as links checked.
        doc = tmp_path.resolve() / "doc.md"
        doc.write_text(
            "[self](#top) [web](https://example.com) [mail](mailto:a@example.com) "
            "[ok](doc.md) [bad](gone.md#x)\n"
        )
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [doc])

        counts, broken = scan_links([])
        assert counts == {
            "markdown_files_scanned": 1,
            "files_skipped_vendored": 0,
            "links_checked": 2,
            "links_resolved": 1,
        }
        assert [b["target"] for b in broken] == ["gone.md#x"]

    def test_vendored_and_deleted_files_are_skipped_and_not_scanned(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        root = tmp_path.resolve()
        monkeypatch.setattr("check_md_links.ROOT", root)
        vendored_doc = root / "vendor" / "SKILL.md"
        vendored_doc.parent.mkdir()
        vendored_doc.write_text("[bad](nope.md)\n")
        local_doc = root / "notes.md"
        local_doc.write_text("[bad](nope.md)\n")
        deleted_doc = root / "GONE.md"  # tracked but not on disk
        registry = [{"path": "vendor", "vendor_mode": "dir"}]
        monkeypatch.setattr(
            "check_md_links.tracked_markdown",
            lambda: [vendored_doc, local_doc, deleted_doc],
        )

        counts, broken = scan_links(registry)
        assert counts["files_skipped_vendored"] == 1
        assert counts["markdown_files_scanned"] == 1
        assert [b["file"] for b in broken] == ["notes.md"]


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
