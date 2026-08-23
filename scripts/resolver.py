# resolver.py for check_md_links JSON output
import json
from enum import Enum


class OutputFormat(Enum):
    HUMAN = 'human'
    JSON = 'json'


class JsonOutput:
    def __init__(self):
        self.passed = True
        self_counts = {
            'markdown_files_scanned': 0,
            'links_resolved': 0,
            'resources_checked': 0,
            'files_skipped_as_vendored': 0
        }
        self.broken_links = []
        self.unlinked_resources = []

    def to_json(self) -> str:
        return json.dumps({
            'passed': self.passed,
            'counts': {
                'markdown_files_scanned': self.counts['markdown_files_scanned'],
                'links_resolved': self.counts['links_resolved'],
                'resources_checked': self.counts['resources_checked'],
                'files_skipped_as_vendored': self.counts['files_skipped_as_vendored']
            },
            'broken_links': [
                {'file': link['file'], 'raw_target': link['raw_target'], 'resolved_path': str(link['resolved_path'])}
                for link in self.broken_links
            ],
            'unlinked_resources': [res['path'] for res in self.unlinked_resources]
        }, default=str)
