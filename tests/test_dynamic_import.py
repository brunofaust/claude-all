"""Tests for the python-style `dynamic_import.py` checker."""

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

from dynamic_import import main


@pytest.mark.parametrize(
    "source",
    [
        'import importlib\n\nm = importlib.import_module("myapp.core")\n',
        'from importlib import import_module as im\n\nm = im("myapp")\n',
        'm = __import__("myapp.core.db")\n',
    ],
)
def test_first_party_dynamic_import_bites(
    tmp_path: Path, source: str, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "mod.py").write_text(source)

    assert main(["--package", "myapp", str(tmp_path)]) == 1
    out = capsys.readouterr()
    assert "dynamic-import" in out.out
    assert "scanned=1 files" in out.err


@pytest.mark.parametrize(
    "source",
    [
        'import importlib\n\nm = importlib.import_module("json")\n',
        "import importlib\n\ndef f(n):\n    return importlib.import_module(n)\n",
        'import importlib\n\nm = importlib.import_module(".x", package="myapp")\n',
        'import importlib\n\nwith ctx():\n    m = importlib.import_module("myapp.core")\n',
        "import myapp.core as core\n",
    ],
)
def test_exempt_shapes_are_clean(tmp_path: Path, source: str) -> None:
    (tmp_path / "mod.py").write_text(source)

    assert main(["--package", "myapp", str(tmp_path)]) == 0


def test_exit_zero(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text('m = __import__("myapp")\n')

    assert main(["--exit-zero", "--package", "myapp", str(tmp_path)]) == 0


def test_zero_files_is_an_error(tmp_path: Path) -> None:
    assert main(["--package", "myapp", str(tmp_path)]) == 2
