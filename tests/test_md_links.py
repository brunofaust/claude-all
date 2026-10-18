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


class TestMainJson:
    """--json mode runs against a fixture repo: ROOT, git listing and discovery are patched."""

    @pytest.fixture
    def fixture_repo(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
        root = tmp_path.resolve()
        monkeypatch.setattr(check_md_links, "ROOT", root)
        (root / "vendored.json").write_text('{"vendored": []}')
        monkeypatch.setattr(
            check_md_links,
            "tracked_markdown",
            lambda: [root / "doc.md"],
        )
        monkeypatch.setattr(check_md_links, "scan_readme_coverage", lambda: (1, []))
        return root

    def test_clean_tree_json_is_ok(
        self, fixture_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (fixture_repo / "doc.md").write_text("[self](doc.md)\n")
        assert main(["--json"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is True
        assert report["error"] is None
        assert report["broken_links"] == []
        assert report["unlinked_resources"] == []
        assert report["counts"] == {
            "markdown_files_scanned": 1,
            "links_checked": 1,
            "links_resolved": 1,
            "resources_checked": 1,
            "files_skipped_vendored": 0,
        }

    def test_broken_link_is_reported_with_target_and_resolved_path(
        self, fixture_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (fixture_repo / "doc.md").write_text("intro\n[gone](missing.md)\n")
        assert main(["--json"]) == 1
        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is False
        assert report["broken_links"] == [
            {
                "file": "doc.md",
                "line": 2,
                "target": "missing.md",
                "resolved_path": "missing.md",
            }
        ]
        assert report["counts"]["links_checked"] == 1
        assert report["counts"]["links_resolved"] == 0

    def test_unlinked_resource_is_reported(
        self,
        fixture_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (fixture_repo / "doc.md").write_text("clean\n")
        unlinked = [{"path": "src/x/a/SKILL.md", "kind": "skill", "name": "a"}]
        monkeypatch.setattr(check_md_links, "scan_readme_coverage", lambda: (2, unlinked))
        assert main(["--json"]) == 1
        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is False
        assert report["unlinked_resources"] == unlinked
        assert report["counts"]["resources_checked"] == 2
        assert report["broken_links"] == []

    def test_default_output_is_unchanged_for_broken_link(
        self, fixture_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (fixture_repo / "doc.md").write_text("[gone](missing.md)\n")
        assert main([]) == 1
        captured = capsys.readouterr()
        assert captured.out == "doc.md:1: broken-link -> missing.md\n"
        assert captured.err == "\n1 finding(s).\n"

    def test_default_output_is_unchanged_for_unlinked_resource(
        self,
        fixture_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (fixture_repo / "doc.md").write_text("clean\n")
        unlinked = [{"path": "src/x/a/SKILL.md", "kind": "skill", "name": "a"}]
        monkeypatch.setattr(check_md_links, "scan_readme_coverage", lambda: (2, unlinked))
        assert main([]) == 1
        assert capsys.readouterr().out == (
            "README.md: undocumented -> skill/a (add a row linking src/x/a/SKILL.md)\n"
        )

    def test_checker_failure_emits_error_object_only(
        self,
        fixture_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def fail() -> list[Path]:
            raise subprocess.CalledProcessError(128, ["git", "ls-files"])

        monkeypatch.setattr(check_md_links, "tracked_markdown", fail)
        assert main(["--json"]) == 1
        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert report["ok"] is False
        assert report["error"]["type"] == "CalledProcessError"
        assert report["counts"] is None
        assert captured.out == json.dumps(report, indent=2) + "\n"
        assert "CalledProcessError" in captured.err

    def test_malformed_vendored_registry_emits_error_object(
        self, fixture_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (fixture_repo / "vendored.json").write_text("{not json")
        assert main(["--json"]) == 1
        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert report["ok"] is False
        assert report["error"]["type"] == "JSONDecodeError"
        assert report["counts"] is None

    def test_discovery_failure_emits_error_object(
        self,
        fixture_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def boom() -> tuple[int, list[dict]]:
            raise RuntimeError("discovery broke")

        monkeypatch.setattr(check_md_links, "scan_readme_coverage", boom)
        assert main(["--json"]) == 1
        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert report["error"] == {"type": "RuntimeError", "message": "discovery broke"}
        assert "discovery broke" in captured.err

    def test_zero_file_scan_exits_zero_and_reports_no_files(
        self,
        fixture_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(check_md_links, "tracked_markdown", lambda: [])
        assert main(["--json"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is True
        assert report["counts"]["markdown_files_scanned"] == 0

    def test_vendored_markdown_is_skipped_and_counted(
        self,
        fixture_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        vendored_dir = fixture_repo / "vendor"
        vendored_dir.mkdir()
        upstream = vendored_dir / "upstream.md"
        upstream.write_text("[up](not-here.md)\n")
        (fixture_repo / "doc.md").write_text("clean\n")
        monkeypatch.setattr(
            check_md_links, "load_registry", lambda: [{"path": "vendor", "vendor_mode": "dir"}]
        )
        monkeypatch.setattr(
            check_md_links,
            "tracked_markdown",
            lambda: [upstream, fixture_repo / "doc.md"],
        )
        assert main(["--json"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is True
        assert report["broken_links"] == []
        assert report["counts"]["files_skipped_vendored"] == 1
        assert report["counts"]["markdown_files_scanned"] == 1

    def test_link_climbing_out_of_repo_is_reported_not_crashed(
        self, fixture_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (fixture_repo / "doc.md").write_text("[up](../../../x.md)\n")
        assert main([]) == 1
        assert capsys.readouterr().out == "doc.md:1: broken-link -> ../../../x.md\n"
        assert main(["--json"]) == 1
        report = json.loads(capsys.readouterr().out)
        assert report["error"] is None
        assert report["broken_links"][0]["target"] == "../../../x.md"
        assert report["broken_links"][0]["resolved_path"].endswith("/x.md")

    def test_human_output_is_empty_on_clean_tree(
        self, fixture_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (fixture_repo / "doc.md").write_text("[self](doc.md)\n")
        assert main([]) == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_exit_code_matches_between_modes(
        self, fixture_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (fixture_repo / "doc.md").write_text("[gone](missing.md)\n")
        human_exit = main([])
        capsys.readouterr()
        json_exit = main(["--json"])
        capsys.readouterr()
        assert human_exit == json_exit == 1

    def test_exit_code_matches_between_modes_for_unlinked_resource(
        self,
        fixture_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (fixture_repo / "doc.md").write_text("clean\n")
        unlinked = [{"path": "src/x/a/SKILL.md", "kind": "skill", "name": "a"}]
        monkeypatch.setattr(check_md_links, "scan_readme_coverage", lambda: (2, unlinked))
        human_exit = main([])
        capsys.readouterr()
        json_exit = main(["--json"])
        capsys.readouterr()
        assert human_exit == json_exit == 1

    def test_exit_code_matches_between_modes_on_clean_tree(
        self, fixture_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (fixture_repo / "doc.md").write_text("[self](doc.md)\n")
        human_exit = main([])
        capsys.readouterr()
        json_exit = main(["--json"])
        capsys.readouterr()
        assert human_exit == json_exit == 0

    def test_diagnostics_during_checks_do_not_reach_json_stdout(
        self,
        fixture_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def noisy_tracked() -> list[Path]:
            print("stray diagnostic")
            return [fixture_repo / "doc.md"]

        (fixture_repo / "doc.md").write_text("[self](doc.md)\n")
        monkeypatch.setattr(check_md_links, "tracked_markdown", noisy_tracked)
        assert main(["--json"]) == 0
        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert report["ok"] is True
        assert "stray diagnostic" in captured.err
