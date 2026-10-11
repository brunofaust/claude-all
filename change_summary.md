# Change Summary

### What was changed
- Fixed test_zero_discovery_manifests_only in tests/test_check_requires.py by removing the creation of a manifest for the instruction snippet. This ensures that manifest discovery returns zero files, making the test validate zero-discovery failure for manifests only.

### Implementation approach
The test was incorrectly creating a manifest for the instruction snippet, which caused manifest discovery to find at least one file. This led to the test expecting a zero-discovery failure but getting a validation failure instead. By removing the manifest creation, the test now correctly sets up a scenario with zero manifests and at least one snippet, triggering the zero-discovery failure for manifests as intended.

### Known limitations or follow-up work
No changes were made to scripts/check_requires.py as the existing implementation already satisfies the ticket requirements:
- On success, it prints a single greppable summary line with the inspected count (to stderr).
- Zero-discovery runs are hard failures with appropriate messages naming the unmatched pattern.
- Existing validation behavior, exit codes, and failure messages are unchanged.
The fix was limited to correcting the test setup to match the test's stated intent.
