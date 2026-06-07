## Adversarial verification — before claiming complete
Before saying "tests pass" / "it works" / "fixed" / "ready to merge":
1. **IDENTIFY** the claim → **RUN** the proving command → **READ** full output → **VERIFY** it matches → **CLAIM** with evidence quoted verbatim.

Forbidden until step 5: "should work", "looks good", "seems to", "probably". Bug-fix check: test passes WITH fix → revert → test must FAIL → restore → passes again.
