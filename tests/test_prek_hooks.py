"""claude-all as a prek/pre-commit hook repo: manifest sync, runner, and --install-hooks."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from claude_all import prek_hooks

REPO = Path(__file__).resolve().parent.parent


def test_manifest_is_in_sync_with_resource_specs() -> None:
    rendered = prek_hooks.render_manifest(prek_hooks.load_hook_specs())
    assert (REPO / ".pre-commit-hooks.yaml").read_text() == rendered, (
        "regenerate: uv run python -m claude_all.prek_hooks --manifest > .pre-commit-hooks.yaml"
    )


def test_every_spec_points_at_an_existing_script_with_unique_id() -> None:
    specs = prek_hooks.load_hook_specs()
    ids = [spec.id for spec in specs]
    assert ids, "no prek_hooks declared in any claude-all.json"
    assert len(ids) == len(set(ids))
    for spec in specs:
        assert spec.script_path.is_file(), spec


def run_check(*argv: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "claude_all.prek_hooks", "--run", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_runner_bites_and_passes_clean(tmp_path: Path) -> None:
    (tmp_path / "utils.py").write_text("x = 1\n")
    assert run_check("junk-drawer", str(tmp_path), cwd=tmp_path).returncode == 1
    (tmp_path / "utils.py").unlink()
    (tmp_path / "orders.py").write_text("x = 1\n")
    assert run_check("junk-drawer", str(tmp_path), cwd=tmp_path).returncode == 0


def test_runner_rejects_unknown_id(tmp_path: Path) -> None:
    result = run_check("no-such-hook", cwd=tmp_path)
    assert result.returncode == 2
    assert "unknown hook id" in result.stderr


def make_project(root: Path) -> None:
    (root / "pyproject.toml").write_text('[project]\nname = "my-app"\n')
    (root / "src" / "my_app").mkdir(parents=True)
    (root / "src" / "my_app" / "__init__.py").write_text("")
    (root / "tests" / "unit").mkdir(parents=True)


def installed(*keys: str) -> dict:
    return {"installs": {key: {"scopes": {"user": {}}} for key in keys}}


def test_layout_detection(tmp_path: Path) -> None:
    make_project(tmp_path)
    layout = prek_hooks.detect_layout(tmp_path)
    assert layout["src"] == "src"
    assert layout["package"] == "my_app"
    assert layout["tests"] == "tests"
    assert layout["unit_tests"] == "tests/unit"
    assert "migrations" not in layout


def test_install_appends_block_to_prek_toml_and_is_idempotent(tmp_path: Path) -> None:
    make_project(tmp_path)
    prek = tmp_path / "prek.toml"
    prek.write_text(
        '[[repos]]\nrepo = "local"\n'
        'hooks = [{ id = "mine", name = "mine", entry = "true", language = "system" }]\n'
    )
    state = installed("skills/regression-gates")

    plan = prek_hooks.plan_install(tmp_path, state, rev="v9.9.9")
    assert plan.target == prek
    prek_hooks.apply_plan(plan)

    text = prek.read_text()
    assert 'id = "mine"' in text
    parsed = tomllib.loads(text)
    ours = [r for r in parsed["repos"] if r["repo"] != "local"]
    assert len(ours) == 1 and ours[0]["rev"] == "v9.9.9"
    assert {"id": "junk-drawer", "args": ["src"]} in ours[0]["hooks"]

    again = prek_hooks.plan_install(tmp_path, state, rev="v9.9.9")
    assert again.new_text == text


def test_install_only_offers_hooks_of_installed_skills(tmp_path: Path) -> None:
    make_project(tmp_path)
    plan = prek_hooks.plan_install(tmp_path, installed("skills/regression-gates"), rev="v1")
    ids = {hook_id for hook_id, _ in plan.hooks}
    assert "junk-drawer" in ids
    assert "model-contract" not in ids


def test_install_skips_hook_whose_placeholder_cannot_be_resolved(tmp_path: Path) -> None:
    make_project(tmp_path)
    plan = prek_hooks.plan_install(tmp_path, installed("skills/regression-gates"), rev="v1")
    assert "migration-head" in plan.skipped


def test_install_into_pre_commit_yaml_under_repos(tmp_path: Path) -> None:
    make_project(tmp_path)
    cfg = tmp_path / ".pre-commit-config.yaml"
    cfg.write_text("repos:\n  - repo: local\n    hooks:\n      - id: mine\n")
    plan = prek_hooks.plan_install(tmp_path, installed("skills/regression-gates"), rev="v1")
    assert plan.target == cfg
    prek_hooks.apply_plan(plan)
    text = cfg.read_text()
    assert text.startswith("repos:\n  # >>> claude-all hooks")
    assert "  - repo: https://github.com/brunofaust/claude-all\n    rev: v1\n" in text
    assert "  - repo: local\n" in text


def test_no_config_creates_prek_toml(tmp_path: Path) -> None:
    make_project(tmp_path)
    plan = prek_hooks.plan_install(tmp_path, installed("skills/regression-gates"), rev="v1")
    assert plan.target == tmp_path / "prek.toml"
    assert plan.old_text == ""
    tomllib.loads(plan.new_text)


def test_cli_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_project(tmp_path)
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(installed("skills/regression-gates")))
    monkeypatch.setattr(prek_hooks, "STATE_FILE", state_file)
    monkeypatch.chdir(tmp_path)
    assert prek_hooks.cmd_install_hooks(assume_yes=True, dry_run=True, rev="v1") == 0
    assert not (tmp_path / "prek.toml").exists()


def test_runner_baseline_seed_then_ratchet(tmp_path: Path) -> None:
    (tmp_path / "utils.py").write_text("x = 1\n")
    baseline = tmp_path / "junk_baseline.txt"
    seed = run_check(
        "junk-drawer", "--baseline", str(baseline), "--update", str(tmp_path), cwd=tmp_path
    )
    assert seed.returncode == 0, seed.stderr
    assert "utils" in baseline.read_text()
    ratchet = ("junk-drawer", "--baseline", str(baseline), str(tmp_path))
    assert run_check(*ratchet, cwd=tmp_path).returncode == 0
    (tmp_path / "helpers.py").write_text("x = 1\n")
    assert run_check(*ratchet, cwd=tmp_path).returncode == 1
