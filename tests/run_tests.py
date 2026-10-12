import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_md_links.py"], capture_output=True, text=True
)
print(result.stdout)
if result.stderr:
    print("STderr:", result.stderr, file=sys.stderr)
sys.exit(result.returncode)
