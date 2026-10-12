import ast
import sys

with open("scripts/check_md_links.py") as f:
    content = f.read()

try:
    ast.parse(content)
    print("Syntax is valid")
except SyntaxError as e:
    print("Syntax error:", e)
    sys.exit(1)
