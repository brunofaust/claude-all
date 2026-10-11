import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_check_requires.py", "-v"],
    capture_output=True,
    text=True,
)
print("STDOUT:")
print(result.stdout)
print("STDERR:")
print(result.stderr, file=sys.stderr)
print("Return code:", result.returncode)
# Extra line to change content
print("Done")
