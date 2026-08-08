# Change Summary

### What was changed (List every file modified, created, or deleted and why)
- `scripts/check_md_links.py`
  - Modified to add a `--json` flag that outputs machine-readable results.
  - Updated to include counts of inspected files, resolved links, and resources.
  - Added structured error reporting for broken links and unlinked resources.
- `tests/test_md_links.py`
  - Added new test cases to verify JSON output behavior.
  - Updated existing tests to ensure compatibility with new output formats.

### Implementation approach (Technical approach and key design decisions)
1. **JSON Output Flag**: Added a `--json` flag to enable machine-readable output. When enabled, the script outputs a JSON object instead of human-readable text.
2. **Output Structure**: The JSON includes:
   - `pass`: Boolean indicating overall success.
   - `counts`: Object with `markdown_files`, `links_resolved`, `resources_checked`, and `files_skipped`.
   - `broken_links`: Array of objects containing `file`, `link`, and `target` for each unresolved link.
   - `unlinked_resources`: Array of paths to resources not linked in README.
3. **Backward Compatibility**: The default output remains human-readable. The `--json` flag is optional and does not affect standard output unless specified.
4. **Testing**: Expanded test coverage to validate both JSON and default output modes, ensuring no regressions in existing functionality.

### Known limitations or follow-up work
- **Error Handling in JSON**: Currently, errors are included in the JSON output but could benefit from additional context (e.g., line numbers) in future enhancements.
- **Line Number Reporting**: The current implementation does not include line numbers for broken links in the JSON output. This could be added to improve diagnostics.
- **Performance**: For extremely large repositories, the JSON output generation might introduce negligible overhead. Monitoring performance impact in large-scale scenarios is recommended.
