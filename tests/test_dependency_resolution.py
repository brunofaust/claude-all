"""Tests for the installer's dependency resolution (`claude-all.json` `requires`).

These are the repo's first tests. They cover the resolver's contract — closure,
transitivity, cycles, external deps, filter-independence — plus the real shipped
manifests, so a rename that breaks the dependency graph fails here and not at a
user's install.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from claude_all.cli import (
    USER_CLAUDE_DIR,
    Item,
    discover,
    in_install_scope,
    load_requires,
    resolve_closure,
    resource_config_path,
    reverse_footprint,
    state_key,
    undo_artifact,
)

# Import the check_requires module functions
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_requires


def make_item(kind: str, name: str, src: Path) -> Item:
    """Build a minimal Item for resolver tests.

    Args:
        kind: Resource kind (``skills`` / ``agents`` / …).
        name: Resource name.
        src: The resource's source path (its parent dir holds `claude-all.json`).
    """
    return Item(kind=kind, subcategory="test", name=name, src=src)


def build_universe(root: Path, graph: dict[str, list[str]]) -> list[Item]:
    """Materialise a synthetic resource universe on disk.

    One dir per resource, each with a `SKILL.md` and — when it has dependencies —
    a `claude-all.json`. The single owner of "make test resources", so the tests
    below never re-implement it.

    Args:
        root: Directory to create the resources under.
        graph: ``{name: [dep key, ...]}`` — the dependency graph to write.

    Returns:
        One :class:`Item` per resource, in ``graph`` order.
    """
    items = []
    for name, requires in graph.items():
        d = root / name
        d.mkdir()
        (d / "SKILL.md").write_text("# x\n")
        if requires:
            (d / "claude-all.json").write_text(json.dumps({"requires": requires}))
        items.append(make_item("skills", name, d / "SKILL.md"))
    return items


def keys(items: list[Item]) -> set[str]:
    """Return the ``kind/name`` key set for *items*."""
    return {state_key(i.kind, i.name) for i in items}


class TestResolveClosure:
    """The transitive, cycle-safe install closure."""

    def test_pulls_transitive_dependencies(self, universe: list[Item]) -> None:
        """Selecting `a` installs `a`, its dep `b`, and `b`'s dep `c` — but not `d`.

        Args:
            universe: The synthetic a->b->c (+d) resource set.
        """
        a = next(i for i in universe if i.name == "a")
        closure, pulled, external = resolve_closure([a], universe)
        assert keys(closure) == {"skills/a", "skills/b", "skills/c"}
        assert set(pulled) == {"skills/b", "skills/c"}
        assert external == []

    def test_no_requires_is_just_itself(self, universe: list[Item]) -> None:
        """A resource with no manifest resolves to only itself.

        Args:
            universe: The synthetic a->b->c (+d) resource set.
        """
        d = next(i for i in universe if i.name == "d")
        closure, pulled, external = resolve_closure([d], universe)
        assert keys(closure) == {"skills/d"}
        assert pulled == [] and external == []

    def test_cycle_terminates(self, tmp_path: Path) -> None:
        """A -> B -> A resolves both exactly once instead of looping forever.

        Args:
            tmp_path: pytest's per-test temporary directory.
        """
        items = build_universe(tmp_path, {"x": ["skills/y"], "y": ["skills/x"]})
        closure, _, _ = resolve_closure([items[0]], items)
        assert keys(closure) == {"skills/x", "skills/y"}

    def test_unknown_dep_is_external_not_installed(self, tmp_path: Path) -> None:
        """A dep naming no known resource (a built-in) is reported, never installed.

        Args:
            tmp_path: pytest's per-test temporary directory.
        """
        items = build_universe(tmp_path, {"solo": ["builtin/code-review"]})
        item = items[0]
        closure, pulled, external = resolve_closure([item], [item])
        assert keys(closure) == {"skills/solo"}
        assert pulled == []
        assert external == ["builtin/code-review"]

    def test_already_selected_dep_not_double_reported(self, universe: list[Item]) -> None:
        """Selecting both `a` and its dep `b` reports only `c` as pulled in.

        Args:
            universe: The synthetic a->b->c (+d) resource set.
        """
        sel = [i for i in universe if i.name in {"a", "b"}]
        closure, pulled, _ = resolve_closure(sel, universe)
        assert keys(closure) == {"skills/a", "skills/b", "skills/c"}
        assert set(pulled) == {"skills/c"}


class TestLoadRequires:
    """Manifest reading is tolerant — a bad manifest yields no deps, never raises."""

    @pytest.mark.parametrize(
        ("manifest", "label"),
        [
            (None, "no manifest at all"),
            ("{not json", "malformed JSON"),
            (json.dumps({"requires": "nope"}), "`requires` is not a list"),
        ],
    )
    def test_unusable_manifest_yields_no_deps(
        self, tmp_path: Path, manifest: str | None, label: str
    ) -> None:
        """Every unusable-manifest shape degrades to "no deps", never an exception.

        Args:
            tmp_path: pytest's per-test temporary directory.
            manifest: Raw `claude-all.json` content, or None to omit the file.
            label: Human-readable case name (surfaces in the assertion message).
        """
        (tmp_path / "SKILL.md").write_text("# x\n")
        if manifest is not None:
            (tmp_path / "claude-all.json").write_text(manifest)
        item = make_item("skills", "n", tmp_path / "SKILL.md")
        assert load_requires(item) == [], label

    def test_flat_agent_uses_prefixed_sibling(self, tmp_path: Path) -> None:
        """A flat agent reads `<name>.claude-all.json`, matching the hook convention.

        Args:
            tmp_path: pytest's per-test temporary directory.
        """
        src = tmp_path / "my-agent.md"
        src.write_text("# a\n")
        item = make_item("agents", "my-agent", src)
        assert resource_config_path(item).name == "my-agent.claude-all.json"


class TestPruneScopeGuard:
    """Prune only ever touches artifacts inside the CURRENT install scope.

    `state.json` records absolute paths. When the state file and `$HOME` disagree —
    a copied state file, a container, a test harness overriding HOME — an unguarded
    prune follows those paths out of its sandbox. This happened for real: a
    sandboxed run against a copied state file unlinked symlinks in the actual home.
    """

    def test_out_of_scope_symlink_is_not_unlinked(self, tmp_path: Path) -> None:
        """A recorded target outside the install roots is left strictly alone.

        Args:
            tmp_path: pytest's per-test temporary directory.
        """
        outsider = tmp_path / "somewhere-else"
        outsider.mkdir()
        link = outsider / "victim"
        link.symlink_to(tmp_path)
        assert link.is_symlink()

        actions = reverse_footprint({"target": str(link), "artifacts": []})

        assert link.is_symlink(), "prune escaped its scope and unlinked a foreign symlink"
        assert actions == []

    def test_out_of_scope_artifacts_are_skipped(self, tmp_path: Path) -> None:
        """A recorded CLAUDE.md / settings artifact outside scope is not rewritten.

        Args:
            tmp_path: pytest's per-test temporary directory.
        """
        foreign_md = tmp_path / "CLAUDE.md"
        foreign_md.write_text(
            "<!-- claude-all:skills/x:start -->\nBODY\n<!-- claude-all:skills/x:end -->\n"
        )
        before = foreign_md.read_text()

        label = undo_artifact(
            {
                "type": "claude_md",
                "file": str(foreign_md),
                "start": "<!-- claude-all:skills/x:start -->",
                "end": "<!-- claude-all:skills/x:end -->",
            }
        )

        assert label == ""
        assert foreign_md.read_text() == before, "prune rewrote a CLAUDE.md outside its scope"

    def test_in_scope_paths_are_recognised(self) -> None:
        """The real install roots ARE in scope, so normal pruning still works."""
        assert in_install_scope(USER_CLAUDE_DIR / "skills" / "anything")
        assert in_install_scope(Path.cwd() / ".claude" / "hooks" / "x.py")
        assert not in_install_scope(Path("/tmp/elsewhere/x"))


class TestCheckRequires:
    """Tests for the check_requires script."""

    def test_success_with_resources_found(self, capsys) -> None:
        """Test successful run when resources are found and no violations exist."""
        with patch("check_requires.load_resource_keys") as mock_load:
            mock_load.return_value = {"skills/test"}

            # Create a temporary claude-all.json with valid requires
            with patch("check_requires.SRC") as mock_src:
                mock_src.__truediv__.return_value.rglob.side_effect = lambda pattern: (
                    [Path("test/claude-all.json")] if pattern == "claude-all.json" else []
                )

                # Mock the file reading
                original_read_text = Path.read_text

                def mock_read_text(self, encoding="utf-8"):
                    if str(self).ends_with("claude-all.json"):
                        return json.dumps({"requires": ["skills/test"]})
                    return original_read_text(self, encoding)

                with patch.object(Path, "read_text", side_effect=mock_read_text):
                    # Also need to mock relative_to
                    def mock_relative_to(self, *args, **kwargs):
                        if str(args[0]) == "test/claude-all.json":
                            return Path("test/claude-all.json")
                        return Path.__dict__["relative_to"](*args, **kwargs)

                    with patch.object(Path, "relative_to", side_effect=mock_relative_to):
                        result = check_requires.main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Inspected 1 resource(s)." in captured.out

    def test_zero_discovery_failure(self, capsys) -> None:
        """Test failure when zero resources are discovered."""
        with patch("check_requires.load_resource_keys") as mock_load:
            mock_load.return_value = set()  # Empty set - zero discovery

            result = check_requires.main()

        assert result == 1
        captured = capsys.readouterr()
        assert "0 resources matched the discovery pattern" in captured.err
        assert "manifest that references no resources is unsafe" in captured.err

    def test_existing_failure_still_works(self, capsys) -> None:
        """Test that genuine validation failures still work as before."""
        with patch("check_requires.load_resource_keys") as mock_load:
            mock_load.return_value = {"skills/existing"}

            # Create a temporary claude-all.json with invalid requires
            with patch("check_requires.SRC") as mock_src:
                mock_src.__truediv__.return_value.rglob.side_effect = lambda pattern: (
                    [Path("test/claude-all.json")] if pattern == "claude-all.json" else []
                )

                # Mock the file reading
                original_read_text = Path.read_text

                def mock_read_text(self, encoding="utf-8"):
                    if str(self).ends_with("claude-all.json"):
                        return json.dumps({"requires": ["skills/nonexistent"]})
                    return original_read_text(self, encoding)

                with patch.object(Path, "read_text", side_effect=mock_read_text):
                    # Also need to mock relative_to
                    def mock_relative_to(self, *args, **kwargs):
                        if str(args[0]) == "test/claude-all.json":
                            return Path("test/claude-all.json")
                        return Path.__dict__["relative_to"](*args, **kwargs)

                    with patch.object(Path, "relative_to", side_effect=mock_relative_to):
                        result = check_requires.main()

        assert result == 1
        captured = capsys.readouterr()
        # Should show the violation
        assert "requires 'skills/nonexistent' — no such resource" in captured.out
        # Should show the summary
        assert "1 dangling/invalid requires entry" in captured.err

    def test_every_requires_target_exists(self) -> None:
        """Every `requires` entry in the repo resolves to a discoverable resource."""
        items = discover([])
        known = {state_key(i.kind, i.name) for i in items}
        dangling = [
            (state_key(i.kind, i.name), dep)
            for i in items
            for dep in load_requires(i)
            if dep not in known
        ]
        assert dangling == [], f"dangling requires: {dangling}"

    def test_ship_pr_pulls_its_agents(self) -> None:
        """Installing ship-pr installs the agents it delegates to."""
        items = discover([])
        ship_pr = next((i for i in items if state_key(i.kind, i.name) == "skills/ship-pr"), None)
        if ship_pr is None:  # pragma: no cover - skill always ships today
            pytest.skip("ship-pr not present")
        closure, _, _ = resolve_closure([ship_pr], items)
        assert {"agents/lint-fixer", "agents/test-runner", "agents/git-committer"} <= keys(closure)
