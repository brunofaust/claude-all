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


def test_collect_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Set up a temporary directory as the root
    root = tmp_path
    # Create vendored.json
    (root / "vendored.json").write_text('{"vendored": []}')
    # Create README.md
    readme = root / "README.md"
    readme.write_text("# README\n")
    # Create a markdown file with a broken link
    md1 = root / "broken.md"
    md1.write_text("See [broken link](missing.md)")
    # Create a markdown file with a good link
    md2 = root / "good.md"
    md2.write_text("See [good link](good.md)")
    (root / "good.md").write_text("Good content")

    # Create a resource that is not linked in the README
    # We'll create a dummy resource file and then mock the discover function to return it.
    # We'll create a simple object that mimics the item from discover.
    # We'll create a class:
    class Item:
        def __init__(self, kind, name, src):
            self.kind = kind
            self.name = name
            self.src = src

    resource_path = root / "resource.txt"
    resource_path.write_text("resource")
    item = Item(kind="test", name="test-resource", src=resource_path)

    # We'll make the files git-tracked
    import subprocess

    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=root, check=True)

    # Monkeypatch the ROOT and the discover function
    import check_md_links

    monkeypatch.setattr(check_md_links, "ROOT", root)
    monkeypatch.setattr("claude_all.cli.discover", lambda _: [item])

    # Call collect_data
    registry: list[dict] = []
    (
        markdown_files_scanned,
        links_resolved,
        files_skipped_as_vendored,
        resources_checked,
        broken_links_raw,
        unlinked_resources_raw,
    ) = check_md_links.collect_data(registry)

    # Assertions
    assert markdown_files_scanned == 2  # broken.md and good.md
    assert links_resolved == 2  # one link in each markdown file
    assert files_skipped_as_vendored == 0
    assert resources_checked == 1
    assert len(broken_links_raw) == 1
    # Check the broken link
    file_rel, line_no, target, resolved_abs = broken_links_raw[0]
    assert file_rel == Path("broken.md")
    assert line_no == 1
    assert target == "missing.md"
    assert resolved_abs == (root / "missing.md").resolve()
    assert len(unlinked_resources_raw) == 1
    assert unlinked_resources_raw[0] == resource_path.relative_to(root)


def test_json_mode_with_broken_link_and_unlinked_resource(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Similar setup as above
    root = tmp_path
    (root / "vendored.json").write_text('{"vendored": []}')
    readme = root / "README.md"
    readme.write_text("# README\n")
    md1 = root / "broken.md"
    md1.write_text("See [broken link](missing.md)")
    md2 = root / "good.md"
    md2.write_text("See [good link](good.md)")
    (root / "good.md").write_text("Good content")
    resource_path = root / "resource.txt"
    resource_path.write_text("resource")

    class Item:
        def __init__(self, kind, name, src):
            self.kind = kind
            self.name = name
            self.src = src

    item = Item(kind="test", name="test-resource", src=resource_path)

    import subprocess

    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=root, check=True)

    import check_md_links

    monkeypatch.setattr(check_md_links, "ROOT", root)
    monkeypatch.setattr("claude_all.cli.discover", lambda _: [item])

    # Test JSON mode
    import json
    import sys
    from io import StringIO

    old_argv = sys.argv
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.argv = ["check_md_links.py", "--json"]
    stdout_capture = StringIO()
    stderr_capture = StringIO()
    sys.stdout = stdout_capture
    sys.stderr = stderr_capture
    try:
        from check_md_links import main

        exit_code = main()
    finally:
        sys.argv = old_argv
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    output = stdout_capture.getvalue().strip()
    err_output = stderr_capture.getvalue().strip()
    data = json.loads(output)

    # Assertions for JSON
    assert data["passed"] is False
    assert data["markdown_files_scanned"] == 2
    assert data["links_resolved"] == 2
    assert data["resources_checked"] == 1
    assert data["files_skipped_as_vendored"] == 0
    assert len(data["broken_links"]) == 1
    broken = data["broken_links"][0]
    assert broken["file"] == "broken.md"
    assert broken["line"] == 1
    assert broken["target"] == "missing.md"
    assert broken["resolved"] == str((root / "missing.md").resolve())
    assert len(data["unlinked_resources"]) == 1
    assert data["unlinked_resources"][0] == str(resource_path.relative_to(root))
    assert exit_code == 1
    # Check stderr: should have the finding count
    assert err_output == "\n2 finding(s)."

    # Also, we can test that without --json, the output is unchanged (we'll do in another test)


def test_non_json_output_unaffected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Use the same setup as above
    root = tmp_path
    (root / "vendored.json").write_text('{"vendored": []}')
    readme = root / "README.md"
    readme.write_text("# README\n")
    md1 = root / "broken.md"
    md1.write_text("See [broken link](missing.md)")
    md2 = root / "good.md"
    md2.write_text("See [good link](good.md)")
    (root / "good.md").write_text("Good content")
    resource_path = root / "resource.txt"
    resource_path.write_text("resource")

    class Item:
        def __init__(self, kind, name, src):
            self.kind = kind
            self.name = name
            self.src = src

    item = Item(kind="test", name="test-resource", src=resource_path)

    import subprocess

    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=root, check=True)

    import check_md_links

    monkeypatch.setattr(check_md_links, "ROOT", root)
    monkeypatch.setattr("claude_all.cli.discover", lambda _: [item])

    # Test without --json
    import sys
    from io import StringIO

    old_argv = sys.argv
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.argv = ["check_md_links.py"]  # no --json
    stdout_capture = StringIO()
    stderr_capture = StringIO()
    sys.stdout = stdout_capture
    sys.stderr = stderr_capture
    try:
        from check_md_links import main

        exit_code = main()
    finally:
        sys.argv = old_argv
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    output = stdout_capture.getvalue().strip()
    err_output = stderr_capture.getvalue().strip()

    # Expected output: two lines (the findings) and then a stderr line
    # The findings are:
    #   broken.md:1: broken-link -> missing.md
    #   README.md: undocumented -> test/test-resource (add a row linking resource.txt)
    # Note: the resource path in the finding is relative to root: resource.txt
    expected_lines = [
        "broken.md:1: broken-link -> missing.md",
        "README.md: undocumented -> test/test-resource (add a row linking resource.txt)",
    ]
    # The output should be each finding on a separate line
    assert output.splitlines() == expected_lines
    assert err_output == "\n2 finding(s)."
    assert exit_code == 1


def test_json_mode_clean_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Set up a temporary directory as the root
    root = tmp_path
    # Create vendored.json
    (root / "vendored.json").write_text('{"vendored": []}')
    # Create README.md with a link to a resource
    readme = root / "README.md"
    readme.write_text("# README\nSee [resource](resource.txt)")
    # Create a markdown file with a valid link
    md1 = root / "doc.md"
    md1.write_text("See [good link](good.md)")
    # Create the target of the link
    (root / "good.md").write_text("Good content")
    # Create the resource file
    resource_path = root / "resource.txt"
    resource_path.write_text("resource")

    # We'll create a dummy resource item for the discover function
    class Item:
        def __init__(self, kind, name, src):
            self.kind = kind
            self.name = name
            self.src = src

    item = Item(kind="test", name="test-resource", src=resource_path)

    # Make the files git-tracked
    import subprocess

    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=root, check=True)

    # Monkeypatch the ROOT and the discover function
    import check_md_links

    monkeypatch.setattr(check_md_links, "ROOT", root)
    monkeypatch.setattr("claude_all.cli.discover", lambda _: [item])

    # Test JSON mode
    import json
    import sys
    from io import StringIO

    old_argv = sys.argv
    sys.argv = ["check_md_links.py", "--json"]
    stdout_capture = StringIO()
    stderr_capture = StringIO()
    sys.stdout = stdout_capture
    sys.stderr = stderr_capture
    try:
        from check_md_links import main

        exit_code = main()
    finally:
        sys.argv = old_argv
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

    output = stdout_capture.getvalue().strip()
    err_output = stderr_capture.getvalue().strip()
    data = json.loads(output)

    # Assertions for JSON
    assert data["passed"] is True
    assert data["markdown_files_scanned"] == 1
    assert data["links_resolved"] == 1
    assert data["resources_checked"] == 1
    assert data["files_skipped_as_vendored"] == 0
    assert len(data["broken_links"]) == 0
    assert len(data["unlinked_resources"]) == 0
    assert exit_code == 0
    # No findings, so nothing printed to stderr
    assert err_output == ""
