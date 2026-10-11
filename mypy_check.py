import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "mypy", "scripts/check_requires.py", "test_logic.py"],
    capture_output=True,
    text=True,
)
print("Mypy output:")
print(result.stdout)
if result.stderr:
    print("Mypy stderr:")
    print(result.stderr)
print("Return code:", result.returncode)
sys.exit(result.returncode)
