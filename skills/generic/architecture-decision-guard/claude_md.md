## Architecture decisions — `architecture-decision-guard` skill
Apply before adding a structural boundary (layer, tier, abstraction, interface, package split) or rolling out a strict lint/complexity gate on an existing codebase.

Rule: don't add a boundary without a concrete present need (real second implementation, dependency direction to enforce, genuine reuse). "We might need it" = YAGNI. Prefer containment over speculative layering.
