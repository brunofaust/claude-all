"""Tests for the reference `prek.toml.example` configs shipped by the style skills.

These files carry a `.example` suffix ON PURPOSE: prek treats every `prek.toml`
under the repo root as a workspace PROJECT, so a file literally named
`prek.toml` inside a skill directory gets loaded and run by this repo's own
gate — and one stale `rev` in it breaks the whole gate with "Failed to init
hooks" before a single check runs.

The suffix costs us the `check-toml` hook, which only matches `*.toml`. These
tests are what buys that coverage back: a reference config a user is told to
copy must at minimum be parseable, or we ship a landmine.
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
    """The file the SKILL.md table links to is actually present.

    Args:
        config: Path to the reference config under test.
    """
    assert config.is_file(), f"{config} is missing — SKILL.md links to it"


@pytest.mark.parametrize("config", REFERENCE_CONFIGS, ids=lambda p: p.parent.name)
def test_reference_config_is_strict_toml(config: Path) -> None:
    """It parses under STRICT TOML, not just prek's more lenient dialect.

    prek accepts multi-line inline tables with trailing commas; `tomllib`, the
    `check-toml` hook and most editors do not. Authoring in the strict subset is
    what keeps a copied config from tripping the user's own tooling on day one.

    Args:
        config: Path to the reference config under test.
    """
    with config.open("rb") as handle:
        tomllib.load(handle)


@pytest.mark.parametrize("config", REFERENCE_CONFIGS, ids=lambda p: p.parent.name)
def test_reference_config_declares_hooks(config: Path) -> None:
    """Every declared repo block actually carries hooks, each with an id.

    Guards the vacuous case: a config that parses but declares nothing would
    satisfy the parse test while being useless to copy.

    Args:
        config: Path to the reference config under test.
    """
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
    """The `.example` suffix is load-bearing — renaming it back breaks this repo's gate.

    Args:
        config: Path to the reference config under test.
    """
    assert config.name.endswith(".example"), (
        "a reference config named exactly `prek.toml` is auto-discovered by prek "
        "as a workspace project and will break this repo's own gate"
    )
