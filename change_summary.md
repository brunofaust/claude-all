# Change Summary

### What was changed
- scripts/check_md_links.py: Added --json flag to output machine-readable JSON. Changed internal functions check_links and check_readme_coverage to return structured data (tuples) for use by both human and JSON output. Updated main to handle the flag and produce JSON output when requested. Updated the module docstring to document the JSON shape.
- tests/test_md_links.py: Updated test_tracked_file_missing_from_disk_is_skipped to expect the new return type from check_links (tuple) and extract the broken links list for assertion.

### Implementation approach
The --json flag is added via argparse. When the flag is present, the script collects the same data as before (broken links, unlinked resources) plus counts (markdown files scanned, links resolved, resources checked, files skipped as vendored). It then outputs a JSON object with the required fields and exits with 0 if passed (no broken links and no unlinked resources) else 1. When the flag is absent, the script behaves exactly as before, printing human-readable findings and the count line to stderr.

The internal functions were refactored to return structured data to avoid duplicating the logic for collecting findings and counts. check_links now returns a tuple of (broken_links_list, markdown_files_scanned, links_resolved, files_skipped_as_vendored). check_readme_coverage returns a tuple of (unlinked_resources_list, resources_checked).

The JSON shape includes:
- passed: boolean
- markdown_files_scanned: int
- links_resolved: int
- resources_checked: int
- files_skipped_as_vendored: int
- broken_links: list of objects with file, line, target, resolved
- unlinked_resources: list of objects with path, kind, name

### Known limitations or follow-up work
- The script still uses subprocess to call git ls-files; this assumes the repository is a git repository and the command is available.
- The JSON output does not include the line number for unlinked resources (as the original human output did not either). The path is given relative to the repository root.
- The resolved path in broken_links is an absolute path; this could be made relative if desired, but the absolute path is useful for debugging.
- No new dependencies were added; only the standard library is used.
