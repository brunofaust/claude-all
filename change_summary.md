# Change Summary

### What was changed
- scripts/check_md_links.py: Completely rewritten to add the `--json` flag for machine-readable output while preserving the original behavior when the flag is not used.
- tests/test_md_links.py: Fixed two E501 errors (line 347 and line 365) and added comprehensive tests for the new `--json` flag.

### Implementation approach
1. Added command-line argument parsing with `argparse` to handle the `--json` flag.
2. Created detailed versions of the link checking and README coverage functions that return both human-readable strings and structured data for JSON output.
3. When `--json` is used, the script outputs a single JSON object to stdout containing:
   - `pass`: boolean indicating overall success/failure
   - `counts`: object with counts of markdown files scanned, links resolved, resources checked, and files skipped as vendored
   - `broken_links`: array of objects, each containing the file, target link, and resolved path that did not exist
   - `unlinked_resources`: array of paths (relative to repository root) of resources not linked from README
4. When `--json` is not used, the script behaves exactly as before (human-readable output to stdout, count to stderr).
5. Updated the module docstring to document the JSON output format.
6. Fixed E501 errors in the test file by shortening overly long docstrings and comments.
7. Added tests for the `--json` flag covering clean trees, broken links, unlinked resources, and verification that default output is unaffected.

### Known limitations or follow-up work
- The resolved path in JSON output is always an absolute path. While this provides precise location information, some consumers might prefer relative paths. However, the ticket did not specify a preference, and absolute paths are unambiguous.
- The JSON output does not include any diagnostic information on stderr (as required by the ticket), but if future enhancements need to output diagnostics, they would go to stderr while JSON remains on stdout.
- The implementation assumes that the `discover` function from `claude_all.cli` is available and returns items with `kind`, `name`, and `src` attributes. This matches the existing codebase contract.
