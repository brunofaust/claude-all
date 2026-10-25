# Change Summary for BDN-2: check_requires.py - fail loudly when dependency scan matches zero files

## What was changed

### claude-all/scripts/check_requires.py
- **Zero-discovery hard failure**: Added check in `main()` — when `load_resource_keys()` returns an empty set (discovery matched zero files/resources), the script now prints `"0 resources matched the discovery pattern — nothing was inspected."` to stderr and exits with code 1. A gate that examined nothing must never exit 0.
- **Inspected N summary line on success**: After all violation and undeclared-ref checks pass, `main()` now prints `inspected {len(known)}` to stdout as a greppable summary line, then returns 0.

### claude-all/tests/test_check_requires.py
- **`test_zero_discovery_fails_closed()`** — verifies that zero discovery exits non-zero with the expected message.
- **`test_inspected_line_on_success()`** — verifies that a successful run prints `inspected N` and exits 0, using the real discovery mechanism.
- **`test_gentine_failure_still_fails()`** — verifies that a genuine missing-resource violation still causes exit 1 with "requires finding" in stderr.
- All 6 tests pass (including the 3 pre-existing tests).

### No changes to:
- `scripts/vendor_sync.py` — noted as having a similar discovery weakness per ticket instructions ("one file per change").
- `vendored.json` semantics or any other validation logic.
- What the checker validates (no changes to `find_violations`, `find_undeclared_instruction_refs`, or resource discovery mechanism).

## Implementation approach

The `main()` function was audited and hardened:

1. **Zero-discovery path** (new): After `known = load_resource_keys()`, check `if not known:` → print zero-discovery message to stderr → return 1. This runs *before* any violation checking, so a gate that inspects nothing always fails visibly.

2. **Success path** (modified): After all findings are collected and printed, if no violations exist, print `inspected {len(known)}` to stdout before the final `return 0`. This follows the repo convention of `scanned=N` used in `gate_denominator.py` and `insert_column_list.py`, adapted as `inspected N` per the ticket's guidance.

The discovery mechanism itself was not restructured — only the exit paths and output were augmented.

## Known limitations / follow-up work

- The zero-discovery message uses a generic pattern name ("0 resources matched the discovery pattern") — if a more specific pattern description is desired later, it could be extracted from the `discover()` logic.
- `scripts/vendor_sync.py` has a similar discovery weakness (its own scan mechanism) but was intentionally not changed per the "one file per change" constraint.
- No new dependencies were added; only existing stdlib (`sys`, `io`, `pathlib`) was used.
- The existing validation behaviour, exit codes, and failure messages are all unchanged for non-zero-discovery cases.

## Test results

All 6 tests in `tests/test_check_requires.py` pass:
- 3 pre-existing tests (unchanged behavior)
- 3 new tests covering the BDN-2 requirements