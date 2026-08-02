'''Check markdown links and resources in the documentation.

When run with --json, outputs a JSON object with the following structure:
{
    "status": "pass" or "fail",
    "counts": {
        "markdown_files_scanned": int,
        "links_resolved": int,
        "resources_checked": int,
        "vendored_files_skipped": int
    },
    "broken_links": [
        {
            "file": "str",
            "link": "str",
            "resolved_path": "str"
        }
    ],
    "unlinked_resources": ["str"]
}'''
import argparse
import json
...

class MarkdownLinkChecker:
    def __init__(self):
        self.broken_links = []
        self.unlinked_resources = []
        self.counts = {
            'markdown_files_scanned': 0,
            'links_resolved': 0,
            'resources_checked': 0,
            'vendored_files_skipped': 0
        }

    def output_results(self, json_mode=False):
        if json_mode:
            result = {
                'status': (
                    'pass'
                    if not (self.broken_links or self.unlinked_resources)
                    else 'fail'
                ),
                'counts': self.counts,
                'broken_links': self.broken_links,
                'unlinked_resources': self.unlinked_resources
            }
            print(
                json.dumps(
                    result,
                    indent=2
                )
            )
        else:
            # Original human-readable output
            ...

    def main(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--json', action='store_true')
        args = parser.parse_args()

        # Existing checking logic here...

        self.output_results(json_mode=args.json)

        return 0 if not (self.broken_links or self.unlinked_resources) else 1

if __name__ == '__main__':
    checker = MarkdownLinkChecker()
    exit_code = checker.main()
    exit(exit_code)
