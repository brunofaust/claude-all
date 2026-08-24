import argparse
import json
import sys


def is_vendored(file_path):
    # Existing implementation to determine if a file is vendored
    return False  # Placeholder, actual logic should be here

def scan_markdown_files():
    # Existing implementation to scan markdown files
    return []  # Placeholder, actual logic should be here

def check_links(markdown_files):
    # Existing implementation to check links
    return [], []  # Placeholder, actual logic should be here

def check_resources(markdown_files):
    # Existing implementation to check resources
    return [], []  # Placeholder, actual logic should be here

def get_vendored_files():
    # Existing implementation to get vendored files
    return []  # Placeholder, actual logic should be here

def main():
    parser = argparse.ArgumentParser(description='Check markdown links and resources.')
    parser.add_argument('--json', action='store_true', help='Output results in JSON format')
    args = parser.parse_args()

    scanned_files = scan_markdown_files()
    resolved_links, broken_links = check_links(scanned_files)
    checked_resources, unlinked_resources = check_resources(scanned_files)
    skipped_vendored_files = get_vendored_files()

    if args.json:
        result = {
            "pass": len(broken_links) == 0 and len(unlinked_resources) == 0,
            "counts": {
                "markdown_files_scanned": len(scanned_files),
                "links_resolved": len(resolved_links),
                "resources_checked": len(checked_resources),
                "vendored_files_skipped": len(skipped_vendored_files)
            },
            "broken_links": [
                {"file": link.file, "raw_link": link.raw, "resolved_path": link.resolved}
                for link in broken_links
            ],
            "unlinked_resources": [
                res.path for res in unlinked_resources
            ]
        }
        print(json.dumps(result, indent=2))
    else:
        # Existing human-readable output logic
        print(f"Markdown Files Scanned: {len(scanned_files)}")
        print(f"Links Resolved: {len(resolved_links)}")
        print(f"Resources Checked: {len(checked_resources)}")
        print(f"Vendored Files Skipped: {len(skipped_vendored_files)}")

        if broken_links:
            print("Broken Links:")
            for link in broken_links:
                print(f"  {link.file}: {link.raw} -> {link.resolved}")

        if unlinked_resources:
            print("Unlinked Resources:")
            for res in unlinked_resources:
                print(f"  {res.path}")

        sys.exit(0 if len(broken_links) == 0 and len(unlinked_resources) == 0 else 1)

if __name__ == "__main__":
    main()
