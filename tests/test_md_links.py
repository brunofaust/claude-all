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
    format_human,
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


def test_tracked_file_missing_from_disk_is_skipped(
    self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # `git ls-files` lists a tracked file even after it's deleted from the
    # working tree but not yet re-staged — check_links() must skip it instead
    # of crashing on read_text(). Regression for the CHANGELOG.md removal,
    # which crashed exactly this way.
    missing = tmp_path / "GONE.md"
    monkeypatch.setattr("check_md_links.tracked_markdown", lambda: [missing])
    result = check_links(registry=[])
    assert result["broken_links"] == []
    assert result["markdown_files_scanned"] == 0
    assert result["links_resolved"] == 0
    assert result["files_skipped_vendored"] == 0


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


def _stub_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    broken: list[dict] | None = None,
    scanned: int = 0,
    links_resolved: int = 0,
    skipped_vendored: int = 0,
    unlinked: list[dict] | None = None,
    resources_checked: int = 0,
) -> None:
    """Point main()'s two checkers at controlled structured results."""
    monkeypatch.setattr(
        check_md_links,
        "check_links",
        lambda registry: {
            "broken_links": broken or [],
            "markdown_files_scanned": scanned,
            "links_resolved": links_resolved,
            "files_skipped_vendored": skipped_vendored,
},
    )
    monkeypatch.setattr(
        check_md_links,
        "check_readme_coverage",
        lambda: {
            "unlinked_resources": unlinked or [],
            "resources_checked": resources_checked,
        },
    )


class TestJsonMode:
    def test_json_clean_tree(self, capsys: pytest.CaptureFixture, monkeypatch) -> None:
        """--json on a clean tree emits a passing machine-readable object and exits 0."""
        _stub_run(
            monkeypatch,
            scanned=7,
            links_resolved=12,
            skipped_vendored=3,
            resources_checked=5,
        )
        code = check_md_links.main(["--json"])
        captured = capsys.readouterr()
        assert code == 0
        data = json.loads(captured.out)  # sole stdout line is valid JSON
        assert data["pass"] is True
        assert data["broken_links"] == []
        assert data["unlinked_resources"] == []
        assert data["counts"] == {
            "markdown_files_scanned": 7,
            "links_resolved": 12,
            "resources_checked": 5,
            "files_skipped_vendored": 3,
        }
        assert captured.err == ""

    def test_json_with_broken_link(
        self, capsys: pytest.CaptureFixture, monkeypatch
    ) -> None:
        """--json carries the containing file, raw target and unresolved path."""
        broken = [
            {
                "containing_file": "src/a/b.md",
                "line_no": 4,
                "target": "refs/audit.md",
                "resolved_path": "src/a/refs/audit.md",
            }
        ]
        _stub_run(monkeypatch, broken=broken, scanned=1, links_resolved=0)
        code = check_md_links.main(["--json"])
        captured = capsys.readouterr()
        assert code == 1
        data = json.loads(captured.out)
        assert data["pass"] is False
        assert data["broken_links"] == broken
        assert "1 finding(s)" in captured.err  # the diagnostic goes to stderr

    def test_json_with_unlinked_resource(
        self, capsys: pytest.CaptureFixture, monkeypatch
    ) -> None:
        """--json reports each unlinked resource's path."""
        unlinked = [{"path": "src/a/SKILL.md", "kind": "skills", "name": "a"}]
        _stub_run(monkeypatch, unlinked=unlinked, resources_checked=1)
        code = check_md_links.main(["--json"])
        captured = capsys.readouterr()
        assert code == 1
        data = json.loads(captured.out)
        assert data["pass"] is False
        assert data["unlinked_resources"] == unlinked
        assert data["broken_links"] == []

    def test_default_output_is_unaffected(
        self, capsys: pytest.CaptureFixture, monkeypatch
    ) -> None:
        """Without --json, stdout stays the human report and exit codes match --json."""
        broken = [
            {
                "containing_file": "src/a/b.md",
                "line_no": 4,
                "target": "refs/audit.md",
                "resolved_path": "src/a/refs/audit.md",
            }
        ]
        unlinked = [{"path": "src/c/SKILL.md", "kind": "skills", "name": "c"}]
        _stub_run(monkeypatch, broken=broken, unlinked=unlinked, resources_checked=1)
        code = check_md_links.main([])
        captured = capsys.readouterr()
        assert code == 1
        expected = format_human(broken, unlinked)
        assert captured.out == "\n".join(expected) + "\n"
        assert f"\n{len(expected)} finding(s)." in captured.err

        # Same input under --json must agree on the exit code.
        code_json = check_md_links.main(["--json"])
        capsys.readouterr()
        assert code_json == code

    def test_json_exit_zero_matches_default(
        self, capsys: pytest.CaptureFixture, monkeypatch
    ) -> None:
        """A clean run exits 0 in both modes."""
        _stub_run(monkeypatch, scanned=1, links_resolved=1, resources_checked=1)
        assert check_md_links.main(["--json"]) == 0
        capsys.readouterr()
        assert check_md_links.main([]) == 0