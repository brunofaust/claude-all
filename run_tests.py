#!/usr/bin/env python3
import sys
import tempfile
import traceback
from pathlib import Path

# Add the repo root to the path so we can import the test module
sys.path.insert(0, str(Path(__file__).parent))

# Import the test module
import tests.test_check_requires as test_module

# List of test functions to run
test_functions = [
    test_module.test_undeclared_reference_is_reported,
    test_module.test_declared_and_non_resource_tokens_pass,
    test_module.test_shipped_instructions_declare_every_reference,
    test_module.test_main_zero_discovery_fails,
    test_module.test_main_success_prints_inspected_count,
    test_module.test_main_failure_behavior_unchanged,
]

# We need to mock the tmp_path fixture for the first two tests.
# We'll create a simple tmp_path factory for the purpose of these tests.
# We'll use the pytest tmp_path fixture by creating a temporary directory.
# But we don't have pytest here. We'll skip the tests that require tmp_path for now.
# Instead, we'll run the tests that don't require tmp_path and then run the ones that do
# by creating a temporary directory.


def test_with_tmp_path(test_func):
    """Run a test function that expects a tmp_path argument."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        try:
            test_func(tmp_path)
            return True, None
        except Exception:
            return False, traceback.format_exc()


def test_without_tmp_path(test_func):
    """Run a test function that does not expect a tmp_path argument."""
    try:
        test_func()
        return True, None
    except Exception:
        return False, traceback.format_exc()


# Map test functions to their runner
test_runners = {
    test_module.test_undeclared_reference_is_reported: test_with_tmp_path,
    test_module.test_declared_and_non_resource_tokens_pass: test_with_tmp_path,
    test_module.test_shipped_instructions_declare_every_reference: test_without_tmp_path,
    test_module.test_main_zero_discovery_fails: test_without_tmp_path,
    test_module.test_main_success_prints_inspected_count: test_without_tmp_path,
    test_module.test_main_failure_behavior_unchanged: test_without_tmp_path,
}

all_passed = True
for test_func, runner in test_runners.items():
    passed, error = runner(test_func)
    if not passed:
        all_passed = False
        print(f"FAILED: {test_func.__name__}")
        print(error)
    else:
        print(f"PASSED: {test_func.__name__}")

if all_passed:
    print("\nAll tests passed.")
    sys.exit(0)
else:
    print("\nSome tests failed.")
    sys.exit(1)
