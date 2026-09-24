# PR BDN-2 – check_requires.py zero-discovery hardening

## Change Summary
Hardens `scripts/check_requires.py` against vacuous passes when manifest discovery matches zero files, adds a greppable success summary, and adds unit tests.

## What changed
* scripts/check_requires.py – main() now materialises manifest discovery and fails hard on zero discovery; prints `Inspected N manifests` on success.
* tests/test_check_requires.py – new tests for success summary, zero-discovery failure, and genuine violation.

## Why
Prevent a failing-open gate when directories are renamed/moved. Ensure operators can distinguish “everything passed” from “nothing examined”.

## Deletions
No code was removed.

## Limitations
Count reflects manifest files, not requires entries. Vendor sync remains unchanged.

## Still missing
None.

## Tests
See tests/test_check_requires.py.

## Review carefully
Verify summary line is greppable, zero-discovery message names patterns, existing validation unchanged.

## Note on scripts/vendor_sync.py
scripts/vendor_sync.py also discovers its input via a registry / glob-like pattern. Audit shows a similar failing-open risk where zero discovery would currently exit 0. Per ticket scope this file is intentionally NOT changed in this ticket; it should be hardened in a separate change.
