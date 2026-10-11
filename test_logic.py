import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
# Import the module after modifying sys.path
import importlib.util

spec = importlib.util.spec_from_file_location("check_requires", "scripts/check_requires.py")
if spec is None or spec.loader is None:
    raise ImportError("Could not load check_requires module")
check_requires = importlib.util.module_from_spec(spec)
sys.modules["check_requires"] = check_requires
spec.loader.exec_module(check_requires)


def run_test_zero_discovery_manifests_only():
    tmp_path = Path(tempfile.mkdtemp())
    # Create instruction snippets but no manifests
    instructions_dir = tmp_path / "src" / "claude_all" / "instructions" / "test"
    instructions_dir.mkdir(parents=True)
    (instructions_dir / "claude_md.md").write_text("See `test-skill`\n")
    (instructions_dir / "claude-all.json").write_text('{"requires": ["skills/test-skill"]}')
    original_repo_root = check_requires.REPO_ROOT
    check_requires.REPO_ROOT = tmp_path
    check_requires.SRC = tmp_path / "src"
    check_requires.INSTRUCTIONS_DIR = tmp_path / "src" / "claude_all" / "instructions"
    try:
        result = check_requires.main()
        print(f"test_zero_discovery_manifests_only result: {result} (expected 2)")
        return result == 2
    finally:
        check_requires.REPO_ROOT = original_repo_root
        check_requires.SRC = original_repo_root / "src"
        check_requires.INSTRUCTIONS_DIR = original_repo_root / "src" / "claude_all" / "instructions"


def run_test_zero_discovery_snippets_only():
    tmp_path = Path(tempfile.mkdtemp())
    # Create manifests but no instruction snippets
    (tmp_path / "src" / "claude_all" / "test-skill" / "claude-all.json").parent.mkdir(parents=True)
    (tmp_path / "src" / "claude_all" / "test-skill" / "claude-all.json").write_text(
        '{"requires": []}'
    )
    original_repo_root = check_requires.REPO_ROOT
    check_requires.REPO_ROOT = tmp_path
    check_requires.SRC = tmp_path / "src"
    check_requires.INSTRUCTIONS_DIR = tmp_path / "src" / "claude_all" / "instructions"
    try:
        result = check_requires.main()
        print(f"test_zero_discovery_snippets_only result: {result} (expected 2)")
        return result == 2
    finally:
        check_requires.REPO_ROOT = original_repo_root
        check_requires.SRC = original_repo_root / "src"
        check_requires.INSTRUCTIONS_DIR = original_repo_root / "src" / "claude_all" / "instructions"


def test_existing_failure_still_fails():
    tmp_path = Path(tempfile.mkdtemp())
    # Create a manifest with a bad requirement
    (tmp_path / "src" / "claude_all" / "test-skill" / "claude-all.json").parent.mkdir(parents=True)
    (tmp_path / "src" / "claude_all" / "test-skill" / "claude-all.json").write_text(
        '{"requires": ["skills/nonexistent"]}'
    )
    original_repo_root = check_requires.REPO_ROOT
    check_requires.REPO_ROOT = tmp_path
    check_requires.SRC = tmp_path / "src"
    check_requires.INSTRUCTIONS_DIR = tmp_path / "src" / "claude_all" / "instructions"
    try:
        result = check_requires.main()
        print(f"test_existing_failure_still_fails result: {result} (expected 1)")
        return result == 1
    finally:
        check_requires.REPO_ROOT = original_repo_root
        check_requires.SRC = original_repo_root / "src"
        check_requires.INSTRUCTIONS_DIR = original_repo_root / "src" / "claude_all" / "instructions"


print("Running manifests only test:")
print(run_test_zero_discovery_manifests_only())
print("Running snippets only test:")
print(run_test_zero_discovery_snippets_only())
print("Running existing failure test:")
print(test_existing_failure_still_fails())
