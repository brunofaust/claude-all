import json
import sys
from pathlib import Path


def main() -> int:

    from . import check_links, check_readme_coverage, is_vendored, tracked_markdown

    registry = json.loads((Path(__file__).resolve().parent.parent / "vendored.json").read_text()).get("vendored", [])
    findings = check_links(registry) + check_readme_coverage()

    if '--json' in sys.argv:
        # JSON output mode
        broken_links = []
        for finding in findings:
            if '.md' in finding and 'broken-link' in finding:
                file, line = finding.split(':')[0], finding.split(':')[1]
                target = finding.split('-->')[1].strip()
                broken_links.append({'file': file, 'line': int(line), 'target': target})

        unlinked_resources = [finding.split('-> ')[1].strip() for finding in findings if '->' in finding]

        tracked_files = tracked_markdown()
        existing_files = [f for f in tracked_files if f.exists()]
        total_files_scanned = len(existing_files)
        vendored_files_skipped = len([f for f in tracked_files if not f.exists() or is_vendored(f, registry)])

        report = {
            'passed': not (broken_links or unlinked_resources),
            'total_files_scanned': total_files_scanned,
            'broken_links': broken_links,
            'unlinked_resources': unlinked_resources,
            'vendored_files_skipped': vendored_files_skipped
        }

        print(json.dumps(report, indent=2))
        return 0 if not (broken_links or unlinked_resources) else 1
    else:
        # Existing text output mode
        for finding in findings:
            print(finding)
        if findings:
            print(f'{len(findings)} finding(s).', file=sys.stderr)
            return 1
        return 0

if __name__ == '__main__':
    raise SystemExit(main())
