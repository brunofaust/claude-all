"""frontmatter_override replaces an upstream key and its folded lines; inject only adds."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from vendor_sync import apply_frontmatter, frontmatter_drift

UPSTREAM = (
    "---\n"
    "name: demo\n"
    "description: >-\n"
    "  A very long upstream description\n"
    "  that spans lines.\n"
    "license: MIT\n"
    "---\n"
    "\n# Body\n"
)


def test_override_replaces_folded_key_and_keeps_the_rest(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text(UPSTREAM)

    assert apply_frontmatter(skill, {"user-invocable": True}, {"description": "Use when demo."})

    text = skill.read_text()
    assert '\ndescription: "Use when demo."\n' in text
    assert "upstream description" not in text and "spans lines" not in text
    assert "license: MIT" in text and "user-invocable: true" in text
    assert text.endswith("\n# Body\n")


def test_override_is_idempotent_and_drift_is_detected(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text(UPSTREAM)
    override = {"description": "Use when demo."}

    assert frontmatter_drift(skill, {}, override)
    assert apply_frontmatter(skill, {}, override)
    assert not frontmatter_drift(skill, {}, override)
    assert not apply_frontmatter(skill, {}, override)


def test_inject_never_overwrites_an_existing_key(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text(UPSTREAM)
    assert not apply_frontmatter(skill, {"license": "Apache-2.0"}, {})
    assert "license: MIT" in skill.read_text()
