"""Every shipped agent pins a current-generation Claude model ID.

A model bump touches every agent by hand; this keeps a stale or bare-alias
``model:`` from slipping through the next one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).resolve().parent.parent / "src" / "claude_all" / "agents"
CURRENT_MODELS = {"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"}
MODEL_LINE = re.compile(r"^model:\s*(\S+)\s*$", re.MULTILINE)


def agent_files() -> list[Path]:
    """Return every agent definition file shipped by the installer.

    Returns:
        Flat ``<name>.md`` agents and folder ``agent.md`` agents, excluding companions.
    """
    return sorted(
        path
        for path in AGENTS_DIR.rglob("*.md")
        if path.name == "agent.md" or (path.parent.parent == AGENTS_DIR and "." not in path.stem)
    )


@pytest.mark.parametrize(
    "agent", agent_files(), ids=lambda path: path.parent.name + "/" + path.name
)
def test_agent_model_is_current_generation(agent: Path) -> None:
    """The frontmatter ``model:`` is one of the current full model IDs.

    Args:
        agent: Agent definition file.
    """
    front_matter = agent.read_text(encoding="utf-8").split("---", 2)[1]
    match = MODEL_LINE.search(front_matter)

    assert match is not None, f"{agent} has no model: line"
    assert match.group(1) in CURRENT_MODELS
