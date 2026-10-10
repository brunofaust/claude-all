import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_md_links.py", "-v"], capture_output=True, text=True
)
print(result.stdout)
if result.stderr:
    print(result.stderr, file=sys.stderr)
exit(result.returncode)
