## Architecture decisions — architecture-decision-guard skill

Before adding a structural boundary (a layer, tier, abstraction, interface, or package split) or rolling out a strict lint/complexity gate on an existing codebase, apply the `architecture-decision-guard` skill.

- **Don't add a boundary without a concrete present need** — a real second implementation today, a dependency direction you'll mechanically enforce, or a genuine reuse boundary. "We might need it" = YAGNI.
- Prefer **containment** (one owner + `banned-api`/TID251) over speculative **layering**; layering you add "for cleanliness" tends to create the DI/base-class puzzles it was meant to avoid.
- Collapsing a speculative split back to containment is healthy, not failure (use `python-module-migration` to do it safely).

Pairs with `brunofaust-python-style` (project structure) and the `prek` skill (gate rollout without a backlog).
