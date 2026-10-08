"""Tests for the python-style `model_contract.py` checker's `no-dataclass` rule.

The rule has NO allowlist: a live object goes in a Pydantic model with
`arbitrary_types_allowed=True` (an isinstance check, still validation), so there
is no structural reason left for a dataclass. These tests pin that the rule bites
on every decorator spelling and that the retired `--allow-dataclass` escape hatch
is refused rather than silently accepted.
"""

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

from model_contract import main


@pytest.mark.parametrize(
    "source",
    [
        "from dataclasses import dataclass\n\n@dataclass\nclass Deps:\n    x: int\n",
        "from dataclasses import dataclass\n\n"
        "@dataclass(frozen=True, slots=True)\nclass Deps:\n    x: int\n",
        "import dataclasses\n\n@dataclasses.dataclass\nclass Deps:\n    x: int\n",
    ],
)
def test_every_dataclass_spelling_is_flagged(
    tmp_path: Path, source: str, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "deps.py"
    target.write_text(source)

    assert main(["--select", "no-dataclass", str(target)]) == 1
    assert "no-dataclass" in capsys.readouterr().out


def test_pydantic_model_is_clean(tmp_path: Path) -> None:
    target = tmp_path / "deps.py"
    target.write_text("from pydantic import BaseModel\n\nclass Deps(BaseModel):\n    x: int\n")

    assert main(["--select", "no-dataclass", str(target)]) == 0


def test_allow_dataclass_flag_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "di.py"
    target.write_text(
        "from dataclasses import dataclass\n\n@dataclass\nclass Container:\n    x: int\n"
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["--allow-dataclass", "di.py=Container", str(target)])
    assert excinfo.value.code == 2
