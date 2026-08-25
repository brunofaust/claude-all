import pytest


def make_item(kind: str, name: str, src: Path) -> Item:
    """Build a minimal Item for resolver tests."""
    return Item(kind=kind, subcategory="test", name=name, src=src)

def build_universe(root: Path, graph: dict[str, list[str]]) -> list[Item]:
    """Materialise a synthetic resource universe on disk."""
    ...  # (unchanged)

class TestZeroDiscoveryFail:
    """zero-resources runs fail with a clear message."""
    def test_zero_resources_fails(self):
        """Running in a dir with no claude-all.json files exits non-zero."""
        with pytest.raises(SystemExit) as exit_info:
            sys.argv = ["check_requires.py"]
            original_discover = claude_all.cli.discover
            claude_all.cli.discover = lambda _: []
            try:
                main()
            finally:
                claude_all.cli.discover = original_discover
            assert exit_info.value.code == 1
        # Verify error message (requires capturing stderr)
        # Implementation note: Actual message verification requires stdout/stderr capture
        # This test structure ensures the exit code behavior

class TestDependencyResolution:
    """Core dependency resolution tests."""
    ...  # (existing test classes preserved)

def main() -> int:
    """Test runner."""
    tests = [TestZeroDiscoveryFail, TestResolveClosure, TestLoadRequires, TestShippedManifests]
    ...  # (existing pytest.main() execution)
