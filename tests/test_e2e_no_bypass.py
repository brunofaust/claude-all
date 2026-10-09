"""Tests for the python-style `e2e_no_bypass.py` checker."""

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

from e2e_no_bypass import main

BASE = ["--package", "myapp", "--entrypoint", "myapp.runner:run"]


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ('from unittest.mock import patch\n\npatch("myapp.core.send")\n', "mock-first-party-patch"),
        (
            "from unittest import mock\nfrom myapp.core import Client\n\n"
            'mock.patch.object(Client, "send")\n',
            "mock-first-party-patch",
        ),
        (
            'import importlib\n\nh = importlib.import_module("myapp.handler")\n\n'
            'def test_x(monkeypatch):\n    monkeypatch.setattr(h, "work", None)\n',
            "mock-first-party-patch",
        ),
        (
            "from unittest.mock import MagicMock\nfrom myapp.core import Client\n\n"
            "MagicMock(spec=Client)\n",
            "mock-first-party-spec",
        ),
        ('def test_x(monkeypatch):\n    monkeypatch.setenv("MODE", "x")\n', "env-setenv"),
        ('import os\n\nos.environ["MODE"] = "x"\n', "env-environ-assign"),
        (
            "import os\nfrom unittest.mock import patch\n\npatch.dict(os.environ, {})\n",
            "env-patch-dict",
        ),
        ("from myapp.runner import run\n", "prod-entrypoint-import"),
    ],
)
def test_bypass_bites(
    tmp_path: Path, source: str, kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "test_flow.py").write_text(source)

    assert main([*BASE, "--e2e-root", str(tmp_path)]) == 1
    out = capsys.readouterr()
    assert kind in out.out
    assert "scanned=1 files" in out.err


@pytest.mark.parametrize(
    "source",
    [
        'from unittest.mock import patch\n\npatch("boto3.client")\n',
        'import os\n\nos.environ["MODE"] = SHARED_ENV["MODE"]\n',
        'from unittest.mock import patch\n\npatch("myapp.sdk.wrapper")\n',
        "from myapp.runner import helper\n",
    ],
)
def test_real_execution_is_clean(tmp_path: Path, source: str) -> None:
    (tmp_path / "test_flow.py").write_text(source)

    argv = [*BASE, "--sdk-boundary", "myapp.sdk.wrapper", "--shared-env", "SHARED_ENV"]
    assert main([*argv, "--e2e-root", str(tmp_path)]) == 0


def test_exit_zero(tmp_path: Path) -> None:
    (tmp_path / "test_flow.py").write_text("from myapp.runner import run\n")

    assert main([*BASE, "--exit-zero", "--e2e-root", str(tmp_path)]) == 0


def test_bad_entrypoint_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "test_flow.py").write_text("x = 1\n")

    assert main(["--package", "myapp", "--entrypoint", "nocolon", "--e2e-root", str(tmp_path)]) == 2


def test_zero_files_is_an_error(tmp_path: Path) -> None:
    assert main([*BASE, "--e2e-root", str(tmp_path)]) == 2
