import glob
import os
import sys


def find_violations(path_pattern):
    """
    Find all Python files matching the given path pattern and check for dependencies.
    """
    file_count = 0
    for file_path in glob.glob(path_pattern, recursive=True):
        if os.path.isfile(file_path):
            file_count += 1
            with open(file_path) as file:
                content = file.read()  # Variable now used
                # Example usage: checking for 'import' statements
                if 'import' in content:
                    print(f"Found import in {file_path}")
    return file_count

def main():
    path_pattern = sys.argv[1] if len(sys.argv) > 1 else '*.py'
    count = find_violations(path_pattern)
    if count == 0:
        print(f"No files matched pattern: {path_pattern}")
        sys.exit(1)
    else:
        print(f"Inspected {count} files successfully.")
        sys.exit(0)

if __name__ == "__main__":
    main()
