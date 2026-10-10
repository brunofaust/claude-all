#!/usr/bin/env python3
"""Execute the test suite for check_requires."""

import subprocess
import sys

if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "run_test.py"]))
