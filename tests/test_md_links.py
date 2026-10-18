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

import check_md_links
from check_md_links import (
    CODE_SPAN,
    LINK,
    check_links,
    check_readme_coverage,
    find_unlinked,
    is_vendored,
    main,
    parse_args,
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


class TestScanAndCoverage:
    @pytest.fixture
    def root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        root = tmp_path.resolve()
        (root / "docs").mkdir()
        (root / "README.md").write_text("")
        monkeypatch.setattr("check_md_links.ROOT", root)
        return root

    def test_scan_links_counts_and_reports_broken_target(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (root / "docs" / "a.md").write_text("ok [t](b.md) bad [x](../gone.md#s)\n")
        (root / "docs" / "b.md").write_text("# b\n")
        monkeypatch.setattr(
            "check_md_links.tracked_markdown",
            lambda: [root / "docs" / "a.md", root / "docs" / "b.md"],
        )

        broken, counts = scan_links(registry=[])

        assert counts == {"markdown_scanned": 2, "vendored_skipped": 0, "links_resolved": 1}
        assert broken == [
            {
                "file": "docs/a.md",
                "line": 1,
                "target": "../gone.md#s",
                "resolved": "gone.md",
            }
        ]

    def test_check_links_renders_broken_link_as_text(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (root / "docs" / "a.md").write_text("[x](missing.md)\n")
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [root / "docs" / "a.md"])

        assert check_links(registry=[]) == ["docs/a.md:1: broken-link -> missing.md"]

    def test_find_unlinked_flags_resource_absent_from_readme(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        src = root / "src" / "demo" / "SKILL.md"
        monkeypatch.setitem(
            sys.modules,
            "claude_all.cli",
            SimpleNamespace(
                discover=lambda filters: [SimpleNamespace(kind="skills", name="demo", src=src)]
            ),
        )

        unlinked, checked = find_unlinked()

        assert checked == 1
        assert unlinked == [{"kind": "skills", "name": "demo", "path": "src/demo/SKILL.md"}]

    def test_check_readme_coverage_renders_unlinked_as_text(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        src = root / "src" / "demo" / "SKILL.md"
        monkeypatch.setitem(
            sys.modules,
            "claude_all.cli",
            SimpleNamespace(
                discover=lambda filters: [SimpleNamespace(kind="skills", name="demo", src=src)]
            ),
        )

        assert check_readme_coverage() == [
            "README.md: undocumented -> skills/demo (add a row linking src/demo/SKILL.md)"
        ]

    def test_parse_args_defaults_to_human_output(self) -> None:
        assert parse_args([]).json is False
        assert parse_args(["--json"]).json is True


class TestJsonOutput:
    """`--json` emits one machine-readable object; default output is unchanged."""

    @pytest.fixture
    def tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        root = tmp_path.resolve()
        (root / "docs").mkdir()
        (root / "README.md").write_text("")
        (root / "vendored.json").write_text(json.dumps({"vendored": []}))
        monkeypatch.setattr("check_md_links.ROOT", root)
        self._discover(monkeypatch, [])
        return root

    @staticmethod
    def _track(monkeypatch: pytest.MonkeyPatch, files: list[Path]) -> None:
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: files)

    @staticmethod
    def _discover(monkeypatch: pytest.MonkeyPatch, items: list[SimpleNamespace]) -> None:
        # Only discover() is stubbed: find_unlinked's README match and count run for real.
        fake_cli = SimpleNamespace(discover=lambda filters: items)
        monkeypatch.setitem(sys.modules, "claude_all.cli", fake_cli)

    @staticmethod
    def _unlinked(monkeypatch: pytest.MonkeyPatch, records: list[dict]) -> None:
        root = Path(check_md_links.ROOT)
        items = [
            SimpleNamespace(kind=r["kind"], name=r["name"], src=root / r["path"]) for r in records
        ]
        TestJsonOutput._discover(monkeypatch, items)

    def test_clean_tree_passes(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tree / "docs" / "a.md").write_text("see [t](target.md)\n")
        (tree / "docs" / "target.md").write_text("# target\n")
        (tree / "README.md").write_text("[demo](src/claude_all/skills/demo/SKILL.md)\n")
        self._discover(
            monkeypatch,
            [
                SimpleNamespace(
                    kind="skills", name="demo", src=tree / "src/claude_all/skills/demo/SKILL.md"
                )
            ],
        )
        self._track(monkeypatch, [tree / "docs" / "a.md", tree / "docs" / "target.md"])

        assert main(["--json"]) == 0

        out = capsys.readouterr().out
        report = json.loads(out)  # only stdout content: must parse as a single object
        assert report == {
            "pass": True,
            "counts": {
                "markdown_scanned": 2,
                "vendored_skipped": 0,
                "links_resolved": 1,
                "resources_checked": 1,
            },
            "broken_links": [],
            "unlinked_resources": [],
        }

    def test_broken_link_is_reported_with_file_target_and_resolved(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tree / "docs" / "a.md").write_text("intro\nsee [x](../missing.md)\n")
        self._track(monkeypatch, [tree / "docs" / "a.md"])

        assert main(["--json"]) == 1

        report = json.loads(capsys.readouterr().out)
        assert report["pass"] is False
        assert report["broken_links"] == [
            {
                "file": "docs/a.md",
                "line": 2,
                "target": "../missing.md",
                "resolved": "missing.md",
            }
        ]
        assert report["unlinked_resources"] == []

    def test_unlinked_resource_is_reported_with_path(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tree / "docs" / "a.md").write_text("no links here\n")
        self._track(monkeypatch, [tree / "docs" / "a.md"])
        self._unlinked(
            monkeypatch,
            [{"kind": "skills", "name": "demo", "path": "src/claude_all/skills/demo/SKILL.md"}],
        )

        assert main(["--json"]) == 1

        report = json.loads(capsys.readouterr().out)
        assert report["pass"] is False
        assert report["broken_links"] == []
        assert report["unlinked_resources"] == [
            {"kind": "skills", "name": "demo", "path": "src/claude_all/skills/demo/SKILL.md"}
        ]

    def test_default_output_is_unchanged_human_text(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tree / "docs" / "a.md").write_text("intro\nsee [x](../missing.md)\n")
        self._track(monkeypatch, [tree / "docs" / "a.md"])

        assert main([]) == 1

        captured = capsys.readouterr()
        assert captured.out == "docs/a.md:2: broken-link -> ../missing.md\n"
        assert captured.err == "\n1 finding(s).\n"
        with pytest.raises(json.JSONDecodeError):
            json.loads(captured.out)

    def test_default_output_lists_unlinked_resource_unchanged(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tree / "docs" / "a.md").write_text("no links here\n")
        self._track(monkeypatch, [tree / "docs" / "a.md"])
        self._unlinked(
            monkeypatch,
            [{"kind": "skills", "name": "demo", "path": "src/claude_all/skills/demo/SKILL.md"}],
        )

        assert main([]) == 1

        captured = capsys.readouterr()
        assert captured.out == (
            "README.md: undocumented -> skills/demo "
            "(add a row linking src/claude_all/skills/demo/SKILL.md)\n"
        )
        assert captured.err == "\n1 finding(s).\n"

    def test_json_and_default_modes_share_exit_code(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tree / "docs" / "a.md").write_text("see [x](../missing.md)\n")
        self._track(monkeypatch, [tree / "docs" / "a.md"])

        default_code = main([])
        capsys.readouterr()
        json_code = main(["--json"])

        assert default_code == json_code == 1

    def test_json_mode_keeps_diagnostics_on_stderr(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tree / "docs" / "a.md").write_text("see [x](../missing.md)\n")
        self._track(monkeypatch, [tree / "docs" / "a.md"])

        assert main(["--json"]) == 1

        captured = capsys.readouterr()
        assert json.loads(captured.out)["pass"] is False
        assert captured.err == "\n1 finding(s).\n"

    def test_vendored_markdown_is_counted_as_skipped_not_scanned(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tree / "vendored.json").write_text(
            json.dumps({"vendored": [{"path": "vendor/x", "vendor_mode": "dir"}]})
        )
        (tree / "vendor" / "x").mkdir(parents=True)
        (tree / "vendor" / "x" / "SKILL.md").write_text("upstream [b](../gone.md)\n")
        (tree / "docs" / "a.md").write_text("clean\n")
        self._track(
            monkeypatch,
            [tree / "vendor" / "x" / "SKILL.md", tree / "docs" / "a.md"],
        )

        assert main(["--json"]) == 0

        report = json.loads(capsys.readouterr().out)
        assert report["pass"] is True
        assert report["counts"]["vendored_skipped"] == 1
        assert report["counts"]["markdown_scanned"] == 1
        assert report["broken_links"] == []

    def test_linked_resource_passes_and_is_counted(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tree / "docs" / "a.md").write_text("clean\n")
        (tree / "README.md").write_text("[demo](src/claude_all/skills/demo/SKILL.md)\n")
        self._track(monkeypatch, [tree / "docs" / "a.md"])
        self._discover(
            monkeypatch,
            [
                SimpleNamespace(
                    kind="skills", name="demo", src=tree / "src/claude_all/skills/demo/SKILL.md"
                )
            ],
        )

        assert main(["--json"]) == 0

        report = json.loads(capsys.readouterr().out)
        assert report["pass"] is True
        assert report["counts"]["resources_checked"] == 1
        assert report["unlinked_resources"] == []
