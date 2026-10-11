## Change Summary

### What was changed
- Modified `scripts/check_requires.py` to implement the required zero-discovery behavior:
  - If no manifest files are found (`manifest_count == 0`), the gate fails with exit code 2 and a message naming the manifest pattern, regardless of whether snippets are present or validation errors exist.
  - If manifest files are present but no snippet files are found (`snippet_count == 0`):
    - If there are validation errors, the gate behaves as before (exit 1 with validation findings).
    - If there are no validation errors, the gate fails with exit code 2 and a message naming the snippet pattern.
  - If both manifests and snippets are present, the gate behaves as before (exit 0 on success, exit 1 on validation failures).
- The inspection count line (`scanned=<number>`) is printed to stderr in all cases:
  - In the zero-discovery cases, it prints `scanned=0`.
  - In the validation failure case, it prints `scanned=<total_discovered>` (manifests + snippets).
  - In the success case, it prints `scanned=<total_discovered>`.
- No changes were made to the validation logic (`find_violations`, `find_undeclared_instruction_refs`, `load_resource_keys`) or to other files.

- Modified `tests/test_check_requires.py` to add tests for zero-discovery scenarios and adjust existing tests to match the new behavior.
- Fixed an import error in `test_logic.py` by using the correct method to load the module from a spec (using `importlib.util.module_from_spec` and handling the case where the spec or loader is None).

### Implementation approach
- The change focuses on the `main()` function, reordering the logic to prioritize the zero-discovery check for missing manifests (unconditional) and then handle missing snippets based on the presence of validation findings.
- The zero-discovery error message is constructed by listing the patterns that matched zero files (manifest pattern, snippet pattern, or both) to match the test expectations.
- The inspection count is printed early in each branch to ensure a single greppable summary line is always output, consistent with other checkers in the codebase.
- All existing validation behavior, exit codes, and failure messages for non-zero-discovery cases are preserved.

### Known limitations or follow-up work
- The implementation assumes that the gate should fail on zero-discovery when manifests are missing unconditionally, but only fail on missing snippets when there are no validation findings. This matches the test expectations but may need refinement if the project's interpretation of "zero-discovery" evolves.
- No new dependencies were introduced.
- The change is limited to the specified files; `scripts/vendor_sync.py` was not modified as per the ticket instructions.