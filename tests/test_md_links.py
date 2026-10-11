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
        result = check_links(registry=[])
        assert result["broken_links"] == []


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


def test_json_clean_tree(monkeypatch, capsys):
    """--json on a clean tree returns passed: true and appropriate counts."""
    import json

    from check_md_links import main

    # Mock the functions that do the heavy lifting
    def mock_check_links(registry):
        return {
            "broken_links": [],
            "scanned_markdown": 5,
            "links_resolved": 10,
            "vendored_skipped": 2,
        }

    def mock_check_readme_coverage():
        return {
            "unlinked_resources": [],
            "resources_checked": 3,
        }

    monkeypatch.setattr("check_md_links.check_links", mock_check_links)
    monkeypatch.setattr("check_md_links.check_readme_coverage", mock_check_readme_coverage)
    # Mock the vendored.json read to avoid file access
    monkeypatch.setattr(
        "pathlib.Path.read_text",
        lambda self: (
            '{"vendored": []}'
            if self.name == "vendored.json"
            else __import__("builtins").Path.read_text(self)
        ),
    )
    # Set argv to simulate --json
    monkeypatch.setattr("sys.argv", ["check_md_links.py", "--json"])
    # Call main
    exit_code = main()
    # Capture stdout and stderr
    captured = capsys.readouterr()
    # Parse JSON output
    output = json.loads(captured.out)
    # Assertions
    assert exit_code == 0
    assert output["passed"] is True
    assert output["markdown_files_scanned"] == 5
    assert output["links_resolved"] == 10
    assert output["resources_checked"] == 3
    assert output["files_skipped_as_vendored"] == 2
    assert output["broken_links"] == []
    assert output["unlinked_resources"] == []
    assert captured.err == ""


def test_json_broken_link(monkeypatch, capsys):
    """--json with a broken link returns passed: false and the broken link in output."""
    import json

    from check_md_links import main

    def mock_check_links(registry):
        return {
            "broken_links": [
                {
                    "file": "docs/README.md",
                    "line": 42,
                    "target": "getting-started.md",
                    "resolved_path": "/absolute/path/to/docs/getting-started.md",
                }
            ],
            "scanned_markdown": 1,
            "links_resolved": 1,
            "vendored_skipped": 0,
        }

    def mock_check_readme_coverage():
        return {
            "unlinked_resources": [],
            "resources_checked": 0,
        }

    monkeypatch.setattr("check_md_links.check_links", mock_check_links)
    monkeypatch.setattr("check_md_links.check_readme_coverage", mock_check_readme_coverage)
    monkeypatch.setattr(
        "pathlib.Path.read_text",
        lambda self: (
            '{"vendored": []}'
            if self.name == "vendored.json"
            else __import__("builtins").Path.read_text(self)
        ),
    )
    monkeypatch.setattr("sys.argv", ["check_md_links.py", "--json"])
    exit_code = main()
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert exit_code == 1  # because there is a broken link
    assert output["passed"] is False
    assert output["markdown_files_scanned"] == 1
    assert output["links_resolved"] == 1
    assert output["resources_checked"] == 0
    assert output["files_skipped_as_vendored"] == 0
    assert len(output["broken_links"]) == 1
    bl = output["broken_links"][0]
    assert bl["file"] == "docs/README.md"
    assert bl["line"] == 42
    assert bl["target"] == "getting-started.md"
    assert bl["resolved_path"] == "/absolute/path/to/docs/getting-started.md"
    assert output["unlinked_resources"] == []
    assert captured.err == ""


def test_json_unlinked_resource(monkeypatch, capsys):
    """--json with an unlinked resource returns passed: false and the resource in output."""
    import json

    from check_md_links import main

    def mock_check_links(registry):
        return {
            "broken_links": [],
            "scanned_markdown": 0,
            "links_resolved": 0,
            "vendored_skipped": 0,
        }

    def mock_check_readme_coverage():
        return {
            "unlinked_resources": [
                {
                    "kind": "skill",
                    "name": "test-skill",
                    "src": "src/skills/test-skill/SKILL.md",
                }
            ],
            "resources_checked": 1,
        }

    monkeypatch.setattr("check_md_links.check_links", mock_check_links)
    monkeypatch.setattr("check_md_links.check_readme_coverage", mock_check_readme_coverage)
    monkeypatch.setattr(
        "pathlib.Path.read_text",
        lambda self: (
            '{"vendored": []}'
            if self.name == "vendored.json"
            else __import__("builtins").Path.read_text(self)
        ),
    )
    monkeypatch.setattr("sys.argv", ["check_md_links.py", "--json"])
    exit_code = main()
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert exit_code == 1  # because there is an unlinked resource
    assert output["passed"] is False
    assert output["markdown_files_scanned"] == 0
    assert output["links_resolved"] == 0
    assert output["resources_checked"] == 1
    assert output["files_skipped_as_vendored"] == 0
    assert output["broken_links"] == []
    assert len(output["unlinked_resources"]) == 1
    ur = output["unlinked_resources"][0]
    assert ur["kind"] == "skill"
    assert ur["name"] == "test-skill"
    assert ur["src"] == "src/skills/test-skill/SKILL.md"
    assert captured.err == ""


def test_non_json_output_unaffected(monkeypatch, capsys):
    """Without --json, output is human-readable and exit codes match JSON mode."""
    import json

    from check_md_links import main

    # First, get the JSON mode output and exit code for a known state
    def mock_check_links(registry):
        return {
            "broken_links": [
                {
                    "file": "docs/README.md",
                    "line": 42,
                    "target": "getting-started.md",
                    "resolved_path": "/absolute/path/to/docs/getting-started.md",
                }
            ],
            "scanned_markdown": 1,
            "links_resolved": 1,
            "vendored_skipped": 0,
        }

    def mock_check_readme_coverage():
        return {
            "unlinked_resources": [
                {
                    "kind": "skill",
                    "name": "test-skill",
                    "src": "src/skills/test-skill/SKILL.md",
                }
            ],
            "resources_checked": 1,
        }

    monkeypatch.setattr("check_md_links.check_links", mock_check_links)
    monkeypatch.setattr("check_md_links.check_readme_coverage", mock_check_readme_coverage)
    monkeypatch.setattr(
        "pathlib.Path.read_text",
        lambda self: (
            '{"vendored": []}'
            if self.name == "vendored.json"
            else __import__("builtins").Path.read_text(self)
        ),
    )

    # Test JSON mode
    monkeypatch.setattr("sys.argv", ["check_md_links.py", "--json"])
    exit_code_json = main()
    captured_json = capsys.readouterr()
    json_output = json.loads(captured_json.out)

    # Test non-JSON mode
    monkeypatch.setattr("sys.argv", ["check_md_links.py"])
    exit_code_plain = main()
    captured_plain = capsys.readouterr()

    # Exit codes should be the same
    assert exit_code_json == exit_code_plain
    # In this case, both should be 1 because we have one broken link and one unlinked resource
    assert exit_code_json == 1
    assert exit_code_plain == 1

    # Non-JSON output should contain the human-readable strings
    out = captured_plain.out
    assert "docs/README.md:42: broken-link -> getting-started.md" in out
    assert (
        "README.md: undocumented -> skill/test-skill (add a row linking "
        "src/skills/test-skill/SKILL.md)" in out
    )
    # Also, the stderr line about findings count
    assert "\n2 finding(s)." in captured_plain.err

    # JSON mode output should be parseable and have the same counts
    assert json_output["passed"] is False
    assert json_output["markdown_files_scanned"] == 1
    assert json_output["links_resolved"] == 1
    assert json_output["resources_checked"] == 1
    assert json_output["files_skipped_as_vendored"] == 0
    assert len(json_output["broken_links"]) == 1
    assert len(json_output["unlinked_resources"]) == 1
