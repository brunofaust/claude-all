import subprocess
import sys

result = subprocess.run([sys.executable, "syntax_check.py"], capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print(result.stderr, file=sys.stderr)
sys.exit(result.returncode)
