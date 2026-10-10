import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_md_links.py", "-v"], capture_output=True, text=True
)
with open("test_output.txt", "w") as f:
    f.write("STDOUT:\n")
    f.write(result.stdout)
    f.write("\nSTDERR:\n")
    f.write(result.stderr)
    f.write("\nReturn code: ")
    f.write(str(result.returncode))
