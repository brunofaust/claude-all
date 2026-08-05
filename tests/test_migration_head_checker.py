"""Tests for the regression-gates `migration_head.py` checker.

This checker shipped with a VACUOUS PASS: it parsed only `ast.Assign`, so a
project whose migrations use the annotated form recent Alembic templates emit
(`revision: str = "0001"`) got zero findings on a genuinely forked graph — the
gate ran, said nothing, exited 0, and the fork shipped. So the tests that matter
are the ones proving it BITES on each finding class, in BOTH assignment forms,
each paired with the clean case that must stay silent.
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
        / "generic"
        / "regression-gates"
        / "checkers"
    ),
)

from migration_head import analyse, parse_file

#: The two ways a migration binds `revision`/`down_revision`. The annotated form
#: is what recent Alembic `script.py.mako` templates emit — parsing only the
#: plain form is the bug this suite pins.
PLAIN = "revision = {rev!r}\ndown_revision = {down!r}\n"
ANNOTATED = "revision: str = {rev!r}\ndown_revision: str | None = {down!r}\n"


def write_tree(root: Path, template: str, migrations: list[tuple[str, str, str | None]]) -> list:
    """Write migrations in `template`'s syntax and return their parsed revisions.

    Args:
        root: Directory to write the migration files into.
        template: `PLAIN` or `ANNOTATED`.
        migrations: `(filename, revision, down_revision)` triples.
    """
    parsed = []
    for filename, rev, down in migrations:
        path = root / filename
        path.write_text(template.format(rev=rev, down=down), encoding="utf-8")
        revision = parse_file(path)
        assert revision is not None, f"{filename} parsed as 'not a migration' using {template!r}"
        parsed.append(revision)
    return parsed


@pytest.mark.parametrize("template", [PLAIN, ANNOTATED], ids=["plain", "annotated"])
def test_detects_fork_in_both_assignment_forms(tmp_path: Path, template: str) -> None:
    """A two-head fork is reported regardless of which assignment form is used.

    The `annotated` case is the regression: it silently reported nothing.

    Args:
        tmp_path: Temporary directory for migration files.
        template: Assignment syntax to use (`PLAIN` or `ANNOTATED`).
    """
    revisions = write_tree(
        tmp_path,
        template,
        [
            ("0001_init.py", "0001_init", None),
            ("0002_a.py", "0002_a", "0001_init"),
            ("0003_fork.py", "0003_fork", "0001_init"),
        ],
    )
    findings = analyse(revisions, label="migrations")
    assert any("2 heads" in f for f in findings), findings


@pytest.mark.parametrize("template", [PLAIN, ANNOTATED], ids=["plain", "annotated"])
def test_linear_chain_is_silent(tmp_path: Path, template: str) -> None:
    """A clean linear chain reports nothing — the no-false-positive pair.

    Args:
        tmp_path: Temporary directory for migration files.
        template: Assignment syntax to use (`PLAIN` or `ANNOTATED`).
    """
    revisions = write_tree(
        tmp_path,
        template,
        [
            ("0001_init.py", "0001_init", None),
            ("0002_a.py", "0002_a", "0001_init"),
        ],
    )
    assert analyse(revisions, label="migrations") == []


def test_detects_duplicate_revision_id(tmp_path: Path) -> None:
    """Two migrations claiming one id are reported, not collapsed into one node.

    Mixed syntax on purpose: the id set that head analysis builds silently
    deduplicates these, so the collision needs its own tracking to surface.

    Args:
        tmp_path: Temporary directory for migration files.
    """
    (tmp_path / "0001_init.py").write_text(
        PLAIN.format(rev="0001_init", down=None), encoding="utf-8"
    )
    (tmp_path / "0002_dup.py").write_text(
        ANNOTATED.format(rev="0002_shared", down="0001_init"), encoding="utf-8"
    )
    (tmp_path / "0003_dup.py").write_text(
        PLAIN.format(rev="0002_shared", down="0001_init"), encoding="utf-8"
    )
    revisions = [
        parse_file(tmp_path / name) for name in ("0001_init.py", "0002_dup.py", "0003_dup.py")
    ]
    # Assert all three parsed BEFORE analysing — same discipline as write_tree().
    # Without this, reverting the annotated-form fix would silently drop
    # 0002_dup.py, leaving one owner and no collision, and the test would still
    # look like it exercised the duplicate path.
    assert all(r is not None for r in revisions), revisions
    findings = analyse([r for r in revisions if r is not None], label="migrations")
    assert any("duplicate revision id" in f and "0002_shared" in f for f in findings), findings


@pytest.mark.parametrize("template", [PLAIN, ANNOTATED], ids=["plain", "annotated"])
def test_detects_dangling_down_revision(tmp_path: Path, template: str) -> None:
    """A `down_revision` naming no existing revision is reported in both forms.

    Args:
        tmp_path: Temporary directory for migration files.
        template: Assignment syntax to use (`PLAIN` or `ANNOTATED`).
    """
    revisions = write_tree(tmp_path, template, [("0002_orphan.py", "0002_orphan", "0001_missing")])
    findings = analyse(revisions, label="migrations")
    assert any("dangling" in f for f in findings), findings


@pytest.mark.parametrize("template", [PLAIN, ANNOTATED], ids=["plain", "annotated"])
def test_detects_over_length_revision_id(tmp_path: Path, template: str) -> None:
    """A revision id past the 32-char `alembic_version.version_num` width is reported.

    Args:
        tmp_path: Temporary directory for migration files.
        template: Assignment syntax to use (`PLAIN` or `ANNOTATED`).
    """
    long_id = "x" * 40
    revisions = write_tree(tmp_path, template, [("0001_long.py", long_id, None)])
    findings = analyse(revisions, label="migrations")
    assert any("exceeds 32 chars" in f for f in findings), findings


def test_non_migration_file_is_ignored(tmp_path: Path) -> None:
    """A module with neither binding is not treated as a migration.

    Args:
        tmp_path: Temporary directory for migration files.
    """
    path = tmp_path / "helpers_module.py"
    path.write_text("VALUE = 1\n", encoding="utf-8")
    assert parse_file(path) is None


def test_unparsable_file_fails_open(tmp_path: Path) -> None:
    """A syntactically invalid file is skipped, not crashed on (documented contract).

    Args:
        tmp_path: Temporary directory for migration files.
    """
    path = tmp_path / "0001_broken.py"
    path.write_text("revision = (((\n", encoding="utf-8")
    assert parse_file(path) is None
