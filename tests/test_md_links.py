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


def _fixture_repo(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    pages: dict[str, str],
    readme: str,
    resources: list[tuple[str, str, str]],
) -> None:
    """Build a throwaway repo tree under `root` and point the gate at it."""
    sys.path.insert(0, str(ROOT / "src"))
    (root / "vendored.json").write_text(json.dumps({"vendored": []}))
    (root / "README.md").write_text(readme)
    for rel, text in pages.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    items = []
    for kind, name, rel in resources:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("# resource\n")
        items.append(SimpleNamespace(kind=kind, name=name, src=root / rel))
    markdown = [root / "README.md"] + [root / rel for rel in pages]
    monkeypatch.setattr(check_md_links, "ROOT", root)
    monkeypatch.setattr(check_md_links, "tracked_markdown", lambda: markdown)
    monkeypatch.setattr("claude_all.cli.discover", lambda _registry: items)


def _run_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["check_md_links.py", "--json"])


CLEAN_README = "[a](skills/a/SKILL.md)\n[doc](docs/a.md)\n"


class TestJsonMode:
    def test_clean_tree_emits_only_a_passing_object(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _fixture_repo(
            monkeypatch,
            tmp_path,
            pages={"docs/a.md": "[back](../README.md)\n"},
            readme=CLEAN_README,
            resources=[("skill", "a", "skills/a/SKILL.md")],
        )
        _run_json(monkeypatch)

        assert main() == 0
        out, err = capsys.readouterr()
        report = json.loads(out)
        assert err == ""
        assert report["passed"] is True
        assert report["broken_links"] == []
        assert report["unlinked_resources"] == []
        assert report["counts"]["files_scanned"] == 2
        assert report["counts"]["links_checked"] == 3
        assert report["counts"]["links_resolved"] == 3
        assert report["counts"]["resources_checked"] == 1

    def test_broken_link_is_reported_with_location_and_resolved_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _fixture_repo(
            monkeypatch,
            tmp_path,
            pages={"docs/a.md": "ok\n[bad](../missing.md)\n"},
            readme=CLEAN_README,
            resources=[("skill", "a", "skills/a/SKILL.md")],
        )
        _run_json(monkeypatch)

        assert main() == 1
        out, err = capsys.readouterr()
        assert err == ""
        report = json.loads(out)
        assert report["passed"] is False
        assert report["broken_links"] == [
            {
                "file": "docs/a.md",
                "line": 2,
                "target": "../missing.md",
                "resolved": "missing.md",
            }
        ]
        assert report["counts"]["links_checked"] == 3
        assert report["counts"]["links_resolved"] == 2

    def test_vendored_and_missing_files_are_counted_not_scanned(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _fixture_repo(
            monkeypatch,
            tmp_path,
            pages={
                "docs/a.md": "[back](../README.md)\n",
                # Vendored: its broken upstream-relative link is exempt, not a finding.
                "vendor/x/SKILL.md": "[upstream](nope.md)\n",
            },
            readme=CLEAN_README,
            resources=[("skill", "a", "skills/a/SKILL.md")],
        )
        (tmp_path / "vendored.json").write_text(
            json.dumps({"vendored": [{"path": "vendor/x", "vendor_mode": "dir"}]})
        )
        # Tracked in the index but deleted from the working tree.
        tracked = [
            tmp_path / "README.md",
            tmp_path / "docs/a.md",
            tmp_path / "vendor/x/SKILL.md",
            tmp_path / "GONE.md",
        ]
        monkeypatch.setattr(check_md_links, "tracked_markdown", lambda: tracked)
        _run_json(monkeypatch)

        assert main() == 0
        report = json.loads(capsys.readouterr().out)
        assert report["passed"] is True
        assert report["broken_links"] == []
        assert report["counts"]["files_scanned"] == 2
        assert report["counts"]["files_skipped_vendored"] == 1
        assert report["counts"]["files_skipped_missing"] == 1

    def test_unlinked_resource_is_reported(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _fixture_repo(
            monkeypatch,
            tmp_path,
            pages={"docs/a.md": "plain\n"},
            readme="[doc](docs/a.md)\n",
            resources=[("skill", "a", "skills/a/SKILL.md")],
        )
        _run_json(monkeypatch)

        assert main() == 1
        report = json.loads(capsys.readouterr().out)
        assert report["passed"] is False
        assert report["broken_links"] == []
        assert report["unlinked_resources"] == [
            {"kind": "skill", "name": "a", "path": "skills/a/SKILL.md"}
        ]

    def test_default_output_for_broken_link_is_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _fixture_repo(
            monkeypatch,
            tmp_path,
            pages={"docs/a.md": "ok\n[bad](../missing.md)\n"},
            readme=CLEAN_README,
            resources=[("skill", "a", "skills/a/SKILL.md")],
        )
        monkeypatch.setattr(sys, "argv", ["check_md_links.py"])

        assert main() == 1
        out, err = capsys.readouterr()
        assert out == "docs/a.md:2: broken-link -> ../missing.md\n"
        assert err == "\n1 finding(s).\n"

    def test_default_output_for_unlinked_resource_is_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _fixture_repo(
            monkeypatch,
            tmp_path,
            pages={"docs/a.md": "plain\n"},
            readme="[doc](docs/a.md)\n",
            resources=[("skill", "a", "skills/a/SKILL.md")],
        )
        monkeypatch.setattr(sys, "argv", ["check_md_links.py"])

        assert main() == 1
        out, err = capsys.readouterr()
        assert out == ("README.md: undocumented -> skill/a (add a row linking skills/a/SKILL.md)\n")
        assert err == "\n1 finding(s).\n"

    def test_default_output_on_clean_tree_is_empty_and_passes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _fixture_repo(
            monkeypatch,
            tmp_path,
            pages={"docs/a.md": "[back](../README.md)\n"},
            readme=CLEAN_README,
            resources=[("skill", "a", "skills/a/SKILL.md")],
        )
        monkeypatch.setattr(sys, "argv", ["check_md_links.py"])

        assert main() == 0
        assert capsys.readouterr() == ("", "")

    def test_zero_files_scanned_is_visible_in_counts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A glob that stopped matching: nothing inspected, exit 0. The count
        # makes that vacuous pass visible to a caller.
        _fixture_repo(monkeypatch, tmp_path, pages={}, readme="", resources=[])
        monkeypatch.setattr(check_md_links, "tracked_markdown", lambda: [])
        _run_json(monkeypatch)

        assert main() == 0
        report = json.loads(capsys.readouterr().out)
        assert report["passed"] is True
        assert report["counts"]["files_scanned"] == 0
        assert report["counts"]["links_checked"] == 0

    def test_internal_failure_is_reported_as_json(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _fixture_repo(monkeypatch, tmp_path, pages={}, readme="", resources=[])

        def explode(_registry: list[dict]) -> dict:
            raise RuntimeError("boom")

        monkeypatch.setattr(check_md_links, "scan_links", explode)
        _run_json(monkeypatch)

        assert main() == 1
        assert json.loads(capsys.readouterr().out) == {
            "passed": False,
            "error": "RuntimeError: boom",
        }


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
