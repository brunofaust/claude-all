import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_check_requires.py", "-v"],
    capture_output=True,
    text=True,
)
print(result.stdout)
print(result.stderr, file=sys.stderr)
sys.exit(result.returncode)
