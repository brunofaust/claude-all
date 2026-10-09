"""Tests for the python-style `masking_or_fallback.py` checker."""

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
        / "python"
        / "brunofaust-python-style"
        / "checkers"
    ),
)

from masking_or_fallback import main


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("def f(org_id):\n    return org_id or 0\n", "identity-or-zero"),
        ('def f(conn):\n    return int(conn.get("org_id") or 0)\n', "identity-or-zero"),
        ('def f(user):\n    return user.token or ""\n', "identity-or-empty"),
        ('def f(c, v):\n    return c(project=v or "", branch=v or "")\n', "identity-kwarg-or"),
    ],
)
def test_identity_fallback_bites(
    tmp_path: Path, source: str, kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "mod.py"
    target.write_text(source)

    assert main([str(tmp_path)]) == 1
    out = capsys.readouterr()
    assert kind in out.out
    assert f"{target.as_posix()}:2:" in out.out
    assert "scanned=1 files" in out.err


def test_non_identity_and_tracing_are_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "mod.py").write_text(
        "def f(r, request_id, items):\n"
        "    a = r.rowcount or 0\n"
        '    b = request_id or ""\n'
        "    c = sorted(items, key=r.k or 0)\n"
        "    return a, b, c, items or []\n"
    )

    assert main([str(tmp_path)]) == 0
    assert "candidates=3" in capsys.readouterr().err


def test_clean_project_without_candidates_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "mod.py").write_text("x = 1\n")

    assert main([str(tmp_path)]) == 0
    assert "scanned=1 files candidates=0" in capsys.readouterr().err


def test_identity_patterns_are_configurable(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def f(slug):\n    return slug or ''\n")

    assert main([str(tmp_path)]) == 0
    assert main(["--identity", "slug", str(tmp_path)]) == 1


def test_allow_name_and_exit_zero(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("def f(org_id):\n    return org_id or 0\n")

    assert main(["--allow-name", "org_id", str(tmp_path)]) == 0
    assert main(["--exit-zero", str(tmp_path)]) == 0


def test_zero_files_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path)]) == 2
    assert "scanned=0" in capsys.readouterr().err


def test_unparsable_file_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("def (:\n")

    assert main([str(tmp_path)]) == 2
