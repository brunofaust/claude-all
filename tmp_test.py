import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def run_test(test_name):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", f"tests/test_check_requires.py::{test_name}", "-v"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    print(f"=== {test_name} ===")
    print(f"returncode: {result.returncode}")
    print(f"stdout:\n{result.stdout}")
    print(f"stderr:\n{result.stderr}")
    return result.returncode == 0


if __name__ == "__main__":
    tests = [
        "test_main_success",
        "test_main_zero_discovery",
        "test_main_failure_still_works",
    ]
    all_passed = True
    for test in tests:
        if not run_test(test):
            all_passed = False
    sys.exit(0 if all_passed else 1)
