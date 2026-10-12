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
        human_findings, _, _ = check_links(registry=[])
        assert human_findings == []


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


def test_json_output_clean_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Set up a temporary git repository
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], check=True, capture_output=True
    )

    # Create vendored.json
    vendored = {
        "vendored": [
            {
                "path": "vendored_dir",
                "vendor_mode": "dir",
            }
        ]
    }
    (tmp_path / "vendored.json").write_text(json.dumps(vendored))

    # Create README.md
    readme_content = """# Test
[resource](resource.txt)
"""
    (tmp_path / "README.md").write_text(readme_content)

    # Create a resource file that is linked in the README
    (tmp_path / "resource.txt").write_text("dummy")

    # Create a markdown file outside vendored
    md1 = tmp_path / "page1.md"
    md1.write_text("See [resource](resource.txt) for more.")

    # Create a markdown file inside vendored (should be skipped)
    vendored_dir = tmp_path / "vendored_dir"
    vendored_dir.mkdir()
    md2 = vendored_dir / "page2.md"
    md2.write_text(
        "See [nonexistent](foo.md)"
    )  # broken link, but should be skipped because vendored

    # Track the markdown files with git
    subprocess.run(["git", "add", "page1.md"], check=True, capture_output=True)
    subprocess.run(["git", "add", "vendored_dir/page2.md"], check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], check=True, capture_output=True)

    # Copy the script to the temporary directory
    script_src = Path(__file__).resolve().parent.parent / "scripts" / "check_md_links.py"
    script_dest = tmp_path / "check_md_links.py"
    script_dest.write_text(script_src.read_text())

    # Create the cli.py for discover
    cli_dir = tmp_path / "src" / "claude_all"
    cli_dir.mkdir(parents=True)
    (cli_dir / "cli.py").write_text(
        """
def discover(args):
    from pathlib import Path
    class Resource:
        def __init__(self, src):
            self.src = src
            self.kind = "file"
            self.name = "resource"
    return [Resource(Path("resource.txt"))]
""".strip()
    )

    # Run without --json
    result_nojson = subprocess.run(
        [sys.executable, str(tmp_path / "check_md_links.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    # Run with --json
    result_json = subprocess.run(
        [sys.executable, str(tmp_path / "check_md_links.py"), "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    # Exit codes should be the same
    assert result_nojson.returncode == result_json.returncode
    # In clean tree, both should be 0
    assert result_nojson.returncode == 0
    assert result_json.returncode == 0
    # Check non-json output: should be empty (no findings)
    assert result_nojson.stdout.strip() == ""
    assert result_nojson.stderr.strip() == ""
    # Check json output
    data = json.loads(result_json.stdout)
    assert data["passed"] is True
    assert (
        data["counts"]["markdown_files_scanned"] == 1
    )  # only page1.md, page2.md is vendored and skipped
    assert data["counts"]["links_resolved"] == 1  # the link in page1.md
    assert data["counts"]["resources_checked"] == 1  # one resource from discover
    assert data["counts"]["files_skipped_vendored"] == 1  # the vendored_dir
    assert data["broken_links"] == []
    assert data["unlinked_resources"] == []  # because the resource is linked in README
    assert result_json.stderr.strip() == ""  # no findings, so no message to stderr


def test_json_output_broken_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Set up a temporary git repository
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], check=True, capture_output=True
    )

    # Create vendored.json (empty vendored list for simplicity)
    vendored = {"vendored": []}
    (tmp_path / "vendored.json").write_text(json.dumps(vendored))

    # Create README.md
    readme_content = "# Test\n[resource](resource.txt)\n"
    (tmp_path / "README.md").write_text(readme_content)

    # Create the resource file
    (tmp_path / "resource.txt").write_text("dummy")

    # Create a markdown file with a broken link
    md1 = tmp_path / "page1.md"
    md1.write_text("See [broken](nonexistent.md) for more.")

    # Track the markdown file
    subprocess.run(["git", "add", "page1.md"], check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], check=True, capture_output=True)

    # Copy the script to the temporary directory
    script_src = Path(__file__).resolve().parent.parent / "scripts" / "check_md_links.py"
    script_dest = tmp_path / "check_md_links.py"
    script_dest.write_text(script_src.read_text())

    # Create the cli.py for discover
    cli_dir = tmp_path / "src" / "claude_all"
    cli_dir.mkdir(parents=True)
    (cli_dir / "cli.py").write_text(
        """
def discover(args):
    from pathlib import Path
    class Resource:
        def __init__(self, src):
            self.src = src
            self.kind = "file"
            self.name = "resource"
    return [Resource(Path("resource.txt"))]
""".strip()
    )

    # Run without --json
    result_nojson = subprocess.run(
        [sys.executable, str(tmp_path / "check_md_links.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    # Run with --json
    result_json = subprocess.run(
        [sys.executable, str(tmp_path / "check_md_links.py"), "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    # Exit codes should be the same
    assert result_nojson.returncode == result_json.returncode
    # Both should be 1 because of the broken link
    assert result_nojson.returncode == 1
    assert result_json.returncode == 1
    # Check non-json output: should contain the human-readable finding
    assert "page1.md:1: broken-link -> broken" in result_nojson.stdout
    assert "1 finding(s)." in result_nojson.stderr
    # Check json output
    data = json.loads(result_json.stdout)
    assert data["passed"] is False
    assert data["counts"]["markdown_files_scanned"] == 1
    assert data["counts"]["links_resolved"] == 1
    assert data["counts"]["resources_checked"] == 1
    assert data["counts"]["files_skipped_vendored"] == 0
    assert len(data["broken_links"]) == 1
    broken = data["broken_links"][0]
    assert broken["file"] == "page1.md"
    assert broken["target"] == "broken"
    assert broken["resolved_path"] == str((tmp_path / "nonexistent.md").resolve())
    assert broken["line"] == 1
    assert data["unlinked_resources"] == []
    # Check stderr: should have the finding count
    assert "1 finding(s)." in result_json.stderr


def test_json_output_unlinked_resource(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Set up a temporary git repository
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], check=True, capture_output=True
    )

    # Create vendored.json (empty)
    vendored = {"vendored": []}
    (tmp_path / "vendored.json").write_text(json.dumps(vendored))

    # Create README.md with no link to the resource
    (tmp_path / "README.md").write_text("# Test\nNo link here.\n")

    # Create the resource file (so it exists, but not linked in README)
    resource_file = tmp_path / "resource.txt"
    resource_file.write_text("dummy")

    # Create a markdown file (no broken links)
    md1 = tmp_path / "page1.md"
    md1.write_text(
        "See [existing](resource.txt) for more."
    )  # this links to resource.txt, but note: the README coverage check is about resources from discover, not about markdown links.

    # Track the markdown file
    subprocess.run(["git", "add", "page1.md"], check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], check=True, capture_output=True)

    # Copy the script to the temporary directory
    script_src = Path(__file__).resolve().parent.parent / "scripts" / "check_md_links.py"
    script_dest = tmp_path / "check_md_links.py"
    script_dest.write_text(script_src.read_text())

    # Create the cli.py for discover: return a resource that is not linked in the README
    cli_dir = tmp_path / "src" / "claude_all"
    cli_dir.mkdir(parents=True)
    (cli_dir / "cli.py").write_text(
        """
def discover(args):
    from pathlib import Path
    class Resource:
        def __init__(self, src):
            self.src = src
            self.kind = "file"
            self.name = "resource"
    return [Resource(Path("resource.txt"))]
""".strip()
    )

    # Run without --json
    result_nojson = subprocess.run(
        [sys.executable, str(tmp_path / "check_md_links.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    # Run with --json
    result_json = subprocess.run(
        [sys.executable, str(tmp_path / "check_md_links.py"), "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    # Exit codes should be the same
    assert result_nojson.returncode == result_json.returncode
    # Both should be 1 because of the unlinked resource
    assert result_nojson.returncode == 1
    assert result_json.returncode == 1
    # Check non-json output: should contain the human-readable finding
    assert "README.md: undocumented -> file/resource" in result_nojson.stdout
    assert "1 finding(s)." in result_nojson.stderr
    # Check json output
    data = json.loads(result_json.stdout)
    assert data["passed"] is False
    assert data["counts"]["markdown_files_scanned"] == 1
    assert data["counts"]["links_resolved"] == 1  # the link in the markdown file to resource.txt
    assert data["counts"]["resources_checked"] == 1
    assert data["counts"]["files_skipped_vendored"] == 0
    assert data["broken_links"] == []
    assert data["unlinked_resources"] == ["resource.txt"]  # relative to ROOT
    # Check stderr: should have the finding count
    assert "1 finding(s)." in result_json.stderr
