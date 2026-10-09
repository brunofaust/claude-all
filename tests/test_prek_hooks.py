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
    (root / "tests" / "unit" / "test_my_app.py").write_text("")


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


def test_layout_ignores_directories_without_matching_files(tmp_path: Path) -> None:
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "infra").mkdir()
    layout = prek_hooks.detect_layout(tmp_path)
    assert "tests" not in layout and "unit_tests" not in layout and "infra" not in layout
    (tmp_path / "tests" / "unit" / "test_x.py").write_text("")
    (tmp_path / "infra" / "main.tf").write_text("")
    layout = prek_hooks.detect_layout(tmp_path)
    assert layout["tests"] == "tests" and layout["unit_tests"] == "tests/unit"
    assert layout["infra"] == "infra"


def test_baseline_identity_is_portable_and_line_shift_safe(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("def f(org_id=None):\n    return g(org_id=org_id or 0)\n")
    baseline = tmp_path / "b.txt"
    args = ("masking-or-fallback", "--baseline", str(baseline))
    assert run_check(*args, "--update", "src", cwd=tmp_path).returncode == 0
    header = baseline.read_text().splitlines()[0]
    assert "claude-all-check masking-or-fallback src" in header
    assert sys.executable not in header and ":2:" not in baseline.read_text()

    (src / "a.py").write_text("\n\n" + (src / "a.py").read_text())
    shifted = run_check(*args, "src", cwd=tmp_path)
    assert shifted.returncode == 0, shifted.stdout + shifted.stderr


GATES = installed("skills/regression-gates")


def test_inline_repos_toml_is_refused_not_corrupted(tmp_path: Path) -> None:
    make_project(tmp_path)
    (tmp_path / "prek.toml").write_text('repos = [{ repo = "local", hooks = [] }]\n')
    with pytest.raises(ValueError, match="would not be valid TOML"):
        prek_hooks.plan_install(tmp_path, GATES, rev="v1")


@pytest.mark.parametrize(
    "text",
    [
        f"{prek_hooks.START}\n[[repos]]\n",
        f"{prek_hooks.START}\n{prek_hooks.END}\n{prek_hooks.START}\n{prek_hooks.END}\n",
        f"{prek_hooks.END}\n{prek_hooks.START}\n",
    ],
)
def test_broken_markers_are_refused(tmp_path: Path, text: str) -> None:
    make_project(tmp_path)
    (tmp_path / "prek.toml").write_text(text)
    with pytest.raises(ValueError, match="markers"):
        prek_hooks.plan_install(tmp_path, GATES, rev="v1")


@pytest.mark.parametrize("repos_line", ["repos: []", "repos:  # mine"])
def test_yaml_repos_variants(tmp_path: Path, repos_line: str) -> None:
    make_project(tmp_path)
    cfg = tmp_path / ".pre-commit-config.yaml"
    cfg.write_text(f"{repos_line}\nexclude: ^vendor/\n")
    plan = prek_hooks.plan_install(tmp_path, GATES, rev="v1")
    assert "  - repo: https://github.com/brunofaust/claude-all\n" in plan.new_text
    assert plan.new_text.rstrip().endswith("exclude: ^vendor/")
    assert "[]" not in plan.new_text
    assert ("# mine" in plan.new_text) == ("# mine" in repos_line)


def test_unknown_hook_id_is_an_error(tmp_path: Path) -> None:
    make_project(tmp_path)
    with pytest.raises(ValueError, match="unknown hook id"):
        prek_hooks.plan_install(tmp_path, GATES, rev="v1", only=["junk-drawr"])


def test_cli_reports_errors_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_project(tmp_path)
    state_file = tmp_path / "state.json"
    state_file.write_text("{not json")
    monkeypatch.setattr(prek_hooks, "STATE_FILE", state_file)
    monkeypatch.chdir(tmp_path)
    assert prek_hooks.cmd_install_hooks(assume_yes=True, dry_run=True, rev="v1") == 2
    assert "claude-all --install-hooks:" in capsys.readouterr().err
