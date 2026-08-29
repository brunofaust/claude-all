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
    BrokenLink,
    CoverageResult,
    LinkCheckResult,
    UnlinkedResource,
    check_links,
    check_readme_coverage,
    display_path,
    human_findings,
    is_vendored,
    json_report,
    main,
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
        assert check_links(registry=[]) == LinkCheckResult()

    def test_broken_link_records_file_target_and_resolved(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # A real tmp tree: the resolved path that does not exist is the payload
        # a --json consumer acts on — it must survive the scan verbatim.
        # .resolve() first: check_links resolves link targets, so a symlinked
        # tmp root (/tmp -> /private/tmp) must match on both sides.
        root = tmp_path.resolve()
        (root / "docs").mkdir()
        page = root / "docs" / "page.md"
        page.write_text("intro [gone](../gone.md) more\n")
        monkeypatch.setattr("check_md_links.ROOT", root)
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [page])

        result = check_links(registry=[])

        assert result.md_files_scanned == 1
        assert result.links_resolved == 1
        assert result.vendored_files_skipped == 0
        assert result.broken == [
            BrokenLink(
                file="docs/page.md",
                line=1,
                target="../gone.md",
                resolved="gone.md",
            )
        ]

    def test_vendored_file_counts_as_skipped(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "vend").mkdir()
        upstream = tmp_path / "vend" / "SKILL.md"
        upstream.write_text("[gone](gone.md)\n")
        monkeypatch.setattr("check_md_links.ROOT", tmp_path)
        monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [upstream])
        registry = [{"path": "vend", "vendor_mode": "dir"}]

        result = check_links(registry=registry)

        assert result.broken == []
        assert result.vendored_files_skipped == 1
        assert result.md_files_scanned == 0


class TestDisplayPath:
    def test_in_repo_path_becomes_root_relative(self) -> None:
        assert display_path(ROOT / "a" / "b.md") == "a/b.md"

    def test_outside_repo_keeps_full_path(self) -> None:
        assert display_path(Path("/elsewhere/b.md")) == "/elsewhere/b.md"


class TestCoverageAndReports:
    def test_check_readme_coverage_counts_resources(self) -> None:
        # Runs against this repo: a clean tree must still PROVE it looked —
        # zero resources_checked is the vacuous pass the counts guard against.
        result = check_readme_coverage()
        assert result.resources_checked > 0
        assert result.unlinked == []

    def test_json_report_shape_on_findings(self) -> None:
        links = LinkCheckResult(
            broken=[BrokenLink(file="a.md", line=3, target="../x.md", resolved="x.md")],
            md_files_scanned=2,
            links_resolved=4,
            vendored_files_skipped=1,
        )
        coverage = CoverageResult(
            unlinked=[UnlinkedResource(kind="skill", name="n", path="p/SKILL.md")],
            resources_checked=5,
        )

        assert json_report(links, coverage) == {
            "passed": False,
            "counts": {
                "md_files_scanned": 2,
                "links_resolved": 4,
                "resources_checked": 5,
                "vendored_files_skipped": 1,
            },
            "broken_links": [
                {"file": "a.md", "line": 3, "target": "../x.md", "resolved": "x.md"}
            ],
            "unlinked_resources": [{"kind": "skill", "name": "n", "path": "p/SKILL.md"}],
        }

    def test_human_findings_match_the_legacy_prose(self) -> None:
        # Byte-identical with what the gate printed before --json existed.
        links = LinkCheckResult(
            broken=[BrokenLink(file="a.md", line=3, target="../x.md", resolved="x.md")]
        )
        coverage = CoverageResult(
            unlinked=[UnlinkedResource(kind="skill", name="n", path="p/SKILL.md")]
        )

        assert human_findings(links, coverage) == [
            "a.md:3: broken-link -> ../x.md",
            "README.md: undocumented -> skill/n (add a row linking p/SKILL.md)",
        ]

    def test_passing_human_run_is_silent(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("check_md_links.check_links", lambda registry: LinkCheckResult())
        monkeypatch.setattr(
            "check_md_links.check_readme_coverage", lambda: CoverageResult()
        )
        assert main([]) == 0
        out, err = capsys.readouterr()
        assert out == ""
        assert err == ""


class TestJsonMode:
    """--json emits one machine-readable object; the human report stays default."""

    def test_clean_tree_reports_passing_counts(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The real tree IS the vacuous-pass detector: a passing report whose
        # counts are zero means a glob stopped matching after a rename.
        assert main(["--json"]) == 0
        out, _ = capsys.readouterr()
        report = json.loads(out)
        assert report["passed"] is True
        assert report["broken_links"] == []
        assert report["unlinked_resources"] == []
        assert report["counts"]["md_files_scanned"] > 0
        assert report["counts"]["links_resolved"] > 0
        assert report["counts"]["resources_checked"] > 0

    def test_broken_link_is_machine_readable(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "check_md_links.check_links",
            lambda registry: LinkCheckResult(
                broken=[
                    BrokenLink(
                        file="area/page.md",
                        line=7,
                        target="../gone.md",
                        resolved="area/gone.md",
                    )
                ],
                md_files_scanned=3,
                links_resolved=5,
            ),
        )
        monkeypatch.setattr(
            "check_md_links.check_readme_coverage",
            lambda: CoverageResult(resources_checked=2),
        )

        assert main(["--json"]) == 1
        out, _ = capsys.readouterr()
        report = json.loads(out)
        assert report["passed"] is False
        assert report["broken_links"] == [
            {
                "file": "area/page.md",
                "line": 7,
                "target": "../gone.md",
                "resolved": "area/gone.md",
            }
        ]
        assert report["unlinked_resources"] == []
        assert report["counts"] == {
            "md_files_scanned": 3,
            "links_resolved": 5,
            "resources_checked": 2,
            "vendored_files_skipped": 0,
        }

    def test_unlinked_resource_is_machine_readable(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "check_md_links.check_links",
            lambda registry: LinkCheckResult(md_files_scanned=3, links_resolved=5),
        )
        monkeypatch.setattr(
            "check_md_links.check_readme_coverage",
            lambda: CoverageResult(
                unlinked=[
                    UnlinkedResource(
                        kind="skill",
                        name="my-skill",
                        path="src/claude_all/skills/generic/my-skill/SKILL.md",
                    )
                ],
                resources_checked=2,
            ),
        )

        assert main(["--json"]) == 1
        out, _ = capsys.readouterr()
        report = json.loads(out)
        assert report["passed"] is False
        assert report["broken_links"] == []
        assert report["unlinked_resources"] == [
            {
                "kind": "skill",
                "name": "my-skill",
                "path": "src/claude_all/skills/generic/my-skill/SKILL.md",
            }
        ]

    def test_default_output_never_becomes_json(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "check_md_links.check_links",
            lambda registry: LinkCheckResult(
                broken=[
                    BrokenLink(
                        file="area/page.md",
                        line=7,
                        target="../gone.md",
                        resolved="area/gone.md",
                    )
                ]
            ),
        )
        monkeypatch.setattr(
            "check_md_links.check_readme_coverage", lambda: CoverageResult()
        )

        assert main([]) == 1
        out, err = capsys.readouterr()
        assert out == "area/page.md:7: broken-link -> ../gone.md\n"
        assert "1 finding(s)." in err
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)


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
