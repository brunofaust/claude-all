import subprocess
import sys

subprocess.run([sys.executable, "-m", "pytest", "tests/test_check_requires.py", "-v"])
