import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_check_requires.py", "-v"],
    capture_output=True,
    text=True,
)

print("STDOUT:")
print(result.stdout)
print("\nSTDERR:")
print(result.stderr)
print(f"\nReturn code: {result.returncode}")
