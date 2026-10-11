import subprocess
import sys

sys.exit(
    subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_check_requires.py", "-v"]
    ).returncode
)
