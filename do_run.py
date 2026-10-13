import subprocess
import sys

result = subprocess.run([sys.executable, "run_tests.py"], capture_output=True, text=True)

print(result.stdout)
print(result.stderr)
print("Return code:", result.returncode)
