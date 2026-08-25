#!/usr/bin/env python3
import argparse
import json
import argparse
import json

"""Gate: relative markdown links resolve, and every resource is linked from the README.
... (remaining unchanged docstring content)
    import argparse
    import json

    """Gate: relative markdown links resolve, and every resource is linked from the README.
    ... (remaining unchanged docstring content)
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    registry = json.loads((ROOT / 'vendored.json').read_text()).get('vendored', [])
    result = check_links(registry) + check_readme_coverage()

    if args.json:
        print(json.dumps({
            'passed': len(result) == 0,
            'counts': {
                'markdown_files': len(tracked_markdown()),
                'links_resolved': sum(1 for md in tracked_markdown() for line in strip_code_blocks(md.read_text()) for target in LINK.findall(CODE_SPAN.sub('', line)) if not target.startswith(SKIP_PREFIX)),
                'resources_checked': sum(1 for item in __import__('claude_all.cli').discover([])),
                'vendored_files_skipped': sum(1 for md in tracked_markdown() if is_vendored(md, registry))
            },
            'broken_links': [{'file': f.split(':')[0], 'target': f.split(':')[2].split(' -> ')[1]} for f in result if 'broken-link' in f],
            'unlinked_resources': [f.split(' -> ')[1].split(' ')[0] for f in result if 'undocumented' in f]
        }))
    else:
        for finding in result:
            print(finding)
        if result:
            print(f'
{len(result)} finding(s).', file=sys.stderr)
        sys.exit(0 if not result else 1)
