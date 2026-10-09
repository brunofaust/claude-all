"""Tests for the regression-gates `hook_registration.py` checker."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent
        / "src"
        / "claude_all"
        / "skills"
        / "generic"
        / "regression-gates"
        / "checkers"
    ),
)

from hook_registration import main

PREK_TOML = """\
[[repos]]
repo = "local"
hooks = [
  { id = "foo", name = "foo", entry = "python scripts/check_foo.py", language = "system" },
  { id = "bar", name = "bar", entry = "python", args = ["-m", "scripts.check_bar"] },
]
# { id = "baz", entry = "python scripts/check_baz.py" }
"""


def make_scripts(root: Path, *names: str) -> None:
    (root / "scripts").mkdir()
    for name in names:
        (root / "scripts" / f"{name}.py").write_text("print('scanned=0')\n")


def test_unregistered_script_bites(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_scripts(tmp_path, "check_foo", "check_bar", "check_baz", "check_foo_extra")
    (tmp_path / "prek.toml").write_text(PREK_TOML)

    assert main(["--root", str(tmp_path)]) == 1
    flagged = sorted(line.split(":")[0] for line in capsys.readouterr().out.splitlines())
    # commented-out registration does not count; a prefix match does not count
    assert flagged == ["scripts/check_baz.py", "scripts/check_foo_extra.py"]


def test_all_registered_is_clean(tmp_path: Path) -> None:
    make_scripts(tmp_path, "check_foo", "check_bar")
    (tmp_path / "prek.toml").write_text(PREK_TOML)

    assert main(["--root", str(tmp_path)]) == 0


def test_pre_commit_yaml_is_searched(tmp_path: Path) -> None:
    make_scripts(tmp_path, "check_foo", "check_gone")
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n- repo: local\n  hooks:\n  - id: foo\n    entry: python scripts/check_foo.py\n"
        "  # - id: gone\n  #   entry: python scripts/check_gone.py\n"
    )

    assert main(["--root", str(tmp_path)]) == 1
    assert main(["--root", str(tmp_path), "--exit-zero"]) == 0


def test_zero_scripts_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "prek.toml").write_text(PREK_TOML)

    assert main(["--root", str(tmp_path)]) == 2


def test_missing_config_fails_closed(tmp_path: Path) -> None:
    make_scripts(tmp_path, "check_foo")

    assert main(["--root", str(tmp_path)]) == 2


def test_toml_11_multiline_inline_table_falls_back_to_text(tmp_path: Path) -> None:
    make_scripts(tmp_path, "check_foo", "check_gone")
    (tmp_path / "prek.toml").write_text(
        '[[repos]]\nrepo = "local"\nhooks = [\n  {\n    id = "foo",\n'
        '    entry = "python scripts/check_foo.py"\n  },\n]\n'
        '# entry = "python scripts/check_gone.py"\n'
    )

    assert main(["--root", str(tmp_path)]) == 1
    (tmp_path / "scripts" / "check_gone.py").unlink()
    assert main(["--root", str(tmp_path)]) == 0
