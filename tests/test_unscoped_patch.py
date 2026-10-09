"""Tests for the mock-drift-sweep `unscoped_patch.py` checker."""

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
        / "mock-drift-sweep"
        / "checkers"
    ),
)

from unscoped_patch import main


def write(tmp_path: Path, name: str, body: str) -> Path:
    tests = tmp_path / "tests"
    tests.mkdir(exist_ok=True)
    (tests / name).write_text(body)
    return tests


@pytest.mark.parametrize(
    ("body", "kind"),
    [
        (
            'from unittest.mock import patch\n\ndef test_x():\n    patch("myapp.a.f").start()\n',
            "patch-start",
        ),
        (
            "from unittest.mock import patch\n\nclass T:\n    def setUp(self):\n"
            '        self.p = patch("myapp.a.f")\n        self.p.start()\n',
            "patch-start",
        ),
        (
            "from unittest.mock import MagicMock\nfrom myapp import a\n\n"
            "def test_x():\n    a.client = MagicMock()\n",
            "attr-assign",
        ),
    ],
)
def test_bites(tmp_path: Path, body: str, kind: str, capsys: pytest.CaptureFixture[str]) -> None:
    tests = write(tmp_path, "test_a.py", body)
    assert main([str(tests)]) == 1
    out, err = capsys.readouterr()
    assert f": {kind}: " in out
    assert "scanned=1" in err


def test_clean_with_scoped_patches(tmp_path: Path) -> None:
    body = (
        "from unittest.mock import MagicMock, patch\nfrom myapp import a\n\n"
        '@patch("myapp.a.g")\ndef test_x(g):\n    with patch("myapp.a.f"):\n        pass\n'
        "    local = MagicMock()\n    local.attr = MagicMock()\n"
    )
    assert main([str(write(tmp_path, "test_a.py", body))]) == 0


def test_allowlist_and_exit_zero(tmp_path: Path) -> None:
    body = 'from unittest.mock import patch\n\npatch("myapp.a.f").start()\n'
    tests = write(tmp_path, "conftest.py", body)
    write(tmp_path, "test_ok.py", "x = 1\n")
    assert main([str(tests)]) == 1
    assert main([str(tests), "--exit-zero"]) == 0
    assert main([str(tests), "--allow", "conftest.py"]) == 0


def test_zero_files_fails_closed(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 2
    tests = write(tmp_path, "conftest.py", "x = 1\n")
    assert main([str(tests), "--allow", "conftest.py"]) == 2
