import argparse
import json
import sys

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
                'broken_links': [
                    {
                        'file': link['file'],
                        'link': link['link'],
                        'resolved_path': link['resolved_path']
                    }
                    for link in self.broken_links
                ],
                'unlinked_resources': self.unlinked_resources
            }
            print(json.dumps(
                result,
                indent=2
            ))
        else:
            # Original human-readable output
            for link in self.broken_links:
                print(f'{link['file']}:{link['line']}: broken-link -> {link['link']}')
            for resource in self.unlinked_resources:
                print(f'README.md: undocumented -> {resource}')
            if self.broken_links or self.unlinked_resources:
                print(f'\n{len(self.broken_links + self.unlinked_resources)} finding(s).')

    def check_links(self, registry):
        # Existing link checking logic
        ...

    def check_readme_coverage(self):
        # Existing coverage logic
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