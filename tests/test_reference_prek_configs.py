"""Tests for the reference `prek.toml.example` configs shipped by the style skills.

The `.example` suffix is deliberate: prek treats any `prek.toml` under the repo as a
workspace project, and one stale `rev` breaks the whole gate. The suffix also skips
`check-toml`, so these tests ensure each config is at least parseable.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent / "src" / "claude_all" / "skills"

REFERENCE_CONFIGS = [
    SKILLS / "python" / "brunofaust-python-style" / "prek.toml.example",
    SKILLS / "frontend" / "brunofaust-frontend-style" / "prek.toml.example",
]


@pytest.mark.parametrize("config", REFERENCE_CONFIGS, ids=lambda p: p.parent.name)
def test_reference_config_exists(config: Path) -> None:
    assert config.is_file(), f"{config} is missing — SKILL.md links to it"


@pytest.mark.parametrize("config", REFERENCE_CONFIGS, ids=lambda p: p.parent.name)
def test_reference_config_is_strict_toml(config: Path) -> None:
    with config.open("rb") as handle:
        tomllib.load(handle)


@pytest.mark.parametrize("config", REFERENCE_CONFIGS, ids=lambda p: p.parent.name)
def test_reference_config_declares_hooks(config: Path) -> None:
    with config.open("rb") as handle:
        data = tomllib.load(handle)

    repos = data.get("repos", [])
    assert repos, f"{config.name} declares no [[repos]]"
    for repo in repos:
        hooks = repo.get("hooks", [])
        assert hooks, f"{config.name}: repo {repo.get('repo')!r} declares no hooks"
        for hook in hooks:
            assert hook.get("id"), f"{config.name}: a hook in {repo.get('repo')!r} has no id"


@pytest.mark.parametrize("config", REFERENCE_CONFIGS, ids=lambda p: p.parent.name)
def test_reference_config_is_not_named_prek_toml(config: Path) -> None:
    assert config.name.endswith(".example"), (
        "a reference config named exactly `prek.toml` is auto-discovered by prek "
        "as a workspace project and will break this repo's own gate"
    )
