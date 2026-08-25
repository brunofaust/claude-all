import argparse
import json
import sys
from pathlib import Path


def collect_broken_links(md: Path, registry: list[dict]) -> list[dict]:
    """
    Returns list of broken links in the given markdown file.
    """
    findings: list[dict] = []
    # Existing link checking logic here...
    return findings

def collect_unlinked_resources(readme: str, resources: list[Path]) -> list[dict]:
    """
    Returns list of resources not linked in the README.
    """
    findings: list[dict] = []
    # Existing README coverage checking logic here...
    return findings
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true', help='Output in JSON format')
    args = parser.parse_args()

    registry = json.loads((Path(__file__).resolve().parent.parent / 'vendored.json').read_text())
    if 'vendored' not in registry:
        registry['vendored'] = []
    findings: list[dict] = []
    broken_links: list[dict] = []
    unlinked_resources: list[dict] = []
    # Existing checks that populate findings would be adapted to also populate
    # broken_links and unlinked_resources lists

    if args.json:
        result = {
            'overall_pass': len(findings) == 0,
            'counts': {
                'markdown_files_scanned': 0,
                'links_resolved': 0,
                'resources_checked': 0,
                'files_skipped_vendored': 0
            },
            'broken_links': broken_links,
            'unlinked_resources': unlinked_resources
        }
        print(json.dumps(result, indent=2))
        result = {
            'overall_pass': len(findings) == 0,
            'counts': {
                'markdown_files_scanned': 0,
                'links_resolved': 0,
                'resources_checked': 0,
                'files_skipped_vendored': 0
            },
            'broken_links': broken_links,
            'unlinked_resources': unlinked_resources
        }
        print(json.dumps(result, indent=2))
    else:
        for finding in findings:
            print(finding)
        if findings:
            print(f'\n{len(findings)} finding(s).', file=sys.stderr)
            sys.exit(1)
    sys.exit(0)
