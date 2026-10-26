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
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [missing])
        result = check_links(registry=[])
        assert result["broken_links"] == []
        assert result["counts"]["markdown_skipped_missing"] == 1
        assert result["counts"]["markdown_scanned"] == 0


def _isolated_repo(monkeypatch: pytest.MonkeyPatch, root: Path, files: dict[str, str]) -> None:
    """Point the gate at a throwaway tree so results never depend on the live repo."""
    monkeypatch.setattr("check_md_links.ROOT", root)
    (root / "vendored.json").write_text(json.dumps({"vendored": []}))
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    monkeypatch.setattr(
        "check_md_links.tracked_markdown",
        lambda: [root / name for name in files if name.endswith(".md")],
    )


def _clean_readme() -> dict:
    return {
        "resources_checked": 2,
        "resources_by_kind": {"skill": 2},
        "unlinked_resources": [],
    }


class TestJsonMode:
    def test_clean_tree_emits_one_ok_object(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _isolated_repo(monkeypatch, tmp_path, {"docs/a.md": "[b](b.md)\n", "docs/b.md": "x\n"})
        monkeypatch.setattr("check_md_links.check_readme_coverage", _clean_readme)

        assert main(["--json"]) == 0
        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert captured.err == ""
        assert report["schema_version"] == 1
        assert report["ok"] is True
        assert report["broken_links"] == []
        assert report["unlinked_resources"] == []
        assert report["counts"]["markdown_tracked"] == 2
        assert report["counts"]["markdown_scanned"] == 2
        assert report["counts"]["links_checked"] == 1
        assert report["counts"]["links_resolved"] == 1
        assert report["counts"]["resources_checked"] == 2
        assert report["counts"]["resources_by_kind"] == {"skill": 2}

    def test_broken_link_is_reported_with_location(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _isolated_repo(monkeypatch, tmp_path, {"docs/a.md": "intro\n[x](../nope.md)\n"})
        monkeypatch.setattr("check_md_links.check_readme_coverage", _clean_readme)

        assert main(["--json"]) == 1
        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is False
        assert report["broken_links"] == [
            {
                "file": "docs/a.md",
                "line": 2,
                "target": "../nope.md",
                "resolved": "nope.md",
            }
        ]
        assert report["counts"]["links_checked"] == 1
        assert report["counts"]["links_resolved"] == 0

    def test_unlinked_resource_is_reported(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _isolated_repo(monkeypatch, tmp_path, {"docs/a.md": "clean\n"})
        monkeypatch.setattr(
            "check_md_links.check_readme_coverage",
            lambda: {
                "resources_checked": 1,
                "resources_by_kind": {"skill": 1},
                "unlinked_resources": [{"kind": "skill", "name": "s", "path": "src/s/SKILL.md"}],
            },
        )

        assert main(["--json"]) == 1
        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is False
        assert report["broken_links"] == []
        assert report["unlinked_resources"] == [
            {"kind": "skill", "name": "s", "path": "src/s/SKILL.md"}
        ]

    def test_git_failure_yields_error_object_and_exit_1(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _isolated_repo(monkeypatch, tmp_path, {})

        def fail() -> list[Path]:
            raise subprocess.CalledProcessError(
                128, ["git", "ls-files"], stderr="fatal: not a git repository"
            )

        monkeypatch.setattr("check_md_links.tracked_markdown", fail)

        assert main(["--json"]) == 1
        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert report["ok"] is False
        assert "not a git repository" in report["error"]
        assert "not a git repository" in captured.err

    def test_vendored_files_are_counted_and_local_only_stays_checked(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _isolated_repo(
            monkeypatch,
            tmp_path,
            {
                "vendor/skill/SKILL.md": "[x](gone.md)\n",
                "vendor/skill/ATTRIBUTION.md": "[y](gone.md)\n",
                "docs/a.md": "clean\n",
            },
        )
        (tmp_path / "vendored.json").write_text(
            json.dumps(
                {
                    "vendored": [
                        {
                            "path": "vendor/skill",
                            "vendor_mode": "dir",
                            "local_only": ["ATTRIBUTION.md"],
                        }
                    ]
                }
            )
        )
        monkeypatch.setattr("check_md_links.check_readme_coverage", _clean_readme)

        assert main(["--json"]) == 1
        report = json.loads(capsys.readouterr().out)
        assert report["counts"]["markdown_tracked"] == 3
        assert report["counts"]["markdown_skipped_vendored"] == 1
        assert report["counts"]["markdown_scanned"] == 2
        assert [b["file"] for b in report["broken_links"]] == ["vendor/skill/ATTRIBUTION.md"]

    def test_zero_scanned_files_is_visible_in_counts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A glob that stopped matching exits 0 with nothing inspected; the counts
        # are what let a caller spot that.
        _isolated_repo(monkeypatch, tmp_path, {})
        monkeypatch.setattr("check_md_links.check_readme_coverage", _clean_readme)

        assert main(["--json"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["counts"]["markdown_tracked"] == 0
        assert report["counts"]["markdown_scanned"] == 0

    def test_resolved_path_is_normalised_and_repo_relative(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _isolated_repo(monkeypatch, tmp_path, {"docs/a.md": "[x](sub/../gone.md)\n"})
        monkeypatch.setattr("check_md_links.check_readme_coverage", _clean_readme)

        assert main(["--json"]) == 1
        report = json.loads(capsys.readouterr().out)
        assert report["broken_links"] == [
            {
                "file": "docs/a.md",
                "line": 1,
                "target": "sub/../gone.md",
                "resolved": "docs/gone.md",
            }
        ]


class TestDefaultMode:
    def test_clean_tree_prints_nothing_and_exits_0(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _isolated_repo(monkeypatch, tmp_path, {"docs/a.md": "[b](b.md)\n", "docs/b.md": "x\n"})
        monkeypatch.setattr("check_md_links.check_readme_coverage", _clean_readme)

        assert main([]) == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_human_lines_and_summary_are_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _isolated_repo(monkeypatch, tmp_path, {"docs/a.md": "intro\n[x](../nope.md)\n"})
        monkeypatch.setattr(
            "check_md_links.check_readme_coverage",
            lambda: {
                "resources_checked": 1,
                "resources_by_kind": {"skill": 1},
                "unlinked_resources": [{"kind": "skill", "name": "s", "path": "src/s/SKILL.md"}],
            },
        )

        assert main([]) == 1
        captured = capsys.readouterr()
        assert captured.out == (
            "docs/a.md:2: broken-link -> ../nope.md\n"
            "README.md: undocumented -> skill/s (add a row linking src/s/SKILL.md)\n"
        )
        assert captured.err == "\n2 finding(s).\n"

    def test_exit_code_matches_json_mode(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _isolated_repo(monkeypatch, tmp_path, {"docs/a.md": "[x](../nope.md)\n"})
        monkeypatch.setattr("check_md_links.check_readme_coverage", _clean_readme)

        default_code = main([])
        json_code = main(["--json"])
        assert default_code == json_code == 1


def test_real_repo_json_clean_run_exits_0() -> None:
    """The live tree passes the gate, and --json says so on stdout alone."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_md_links.py"), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert report["ok"] is True
    assert report["counts"]["markdown_scanned"] > 0
    assert report["counts"]["resources_checked"] > 0


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
