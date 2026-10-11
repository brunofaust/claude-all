#!/usr/bin/env python3
import py_compile
import sys

for file in ["scripts/check_md_links.py", "tests/test_md_links.py"]:
    try:
        py_compile.compile(file, doraise=True)
        print(f"{file}: Syntax OK")
    except Exception as e:
        print(f"{file}: Syntax Error: {e}")
        sys.exit(1)
