## Adversarial verification — before claiming complete

Before saying "tests pass" / "it works" / "fixed" / "ready to merge" / "done", apply the `adversarial-verification` skill:

1. **IDENTIFY** the specific claim
1. **RUN** the command that proves it
1. **READ** the full output (exit code + last 20 lines)
1. **VERIFY** output matches the claim
1. **CLAIM** only now, with evidence quoted verbatim

Forbidden phrases until step 5: "should work", "looks good", "seems to", "probably", "I think it's working". If you typed one, restart the gate.

**Bug-fix regression check:** test passes WITH fix → revert fix → test must FAIL → restore fix → test passes again. A test that passes before and after the change proves nothing.

**Try-to-break probe:** at least one failure-case input per claim. Edge / concurrent / missing dep / stale state.
